/**
 * Worktree Sandbox — native Hermes Desktop half.
 *
 * A docked inspector for the plugin's isolated Git worktrees: live diff stats, per-worktree
 * promote/discard, the speculative race leaderboard, and a status-bar chip. It talks to the
 * plugin's own backend (`/api/plugins/worktree-sandbox/...` via `ctx.rest`) and to the gateway
 * event stream (`plugin.worktree-sandbox.*`).
 *
 * Constraints this file lives under (catalog rule 8): uncompiled ESM, only `@hermes/plugin-sdk`,
 * `react` and `react/jsx-runtime`, no JSX syntax, no `document` reach-in, no `eval`, and every
 * timer/listener owned by `ctx` so a disable or reload tears it down. The SDK is imported as a
 * namespace and every newer surface is feature-detected, so an older Desktop build still loads.
 */
import * as sdk from '@hermes/plugin-sdk'
import { useCallback, useEffect, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const PLUGIN_ID = 'worktree-sandbox'
const UPDATED_EVENT = `plugin.${PLUGIN_ID}.updated`
const POLL_MS = 4000

// Area constants with string fallbacks: a build that does not export one still loads.
const AREA_PANES = sdk.PANES_AREA || 'panes'
const AREA_STATUS_RIGHT = (sdk.STATUSBAR_AREAS && sdk.STATUSBAR_AREAS.right) || 'statusBar.right'
const AREA_PALETTE = sdk.PALETTE_AREA || 'palette'
const AREA_DIRECTIVE = sdk.TRANSCRIPT_DIRECTIVE_AREA

const host = sdk.host

const clampText = (value, max) => {
  const text = value == null ? '' : String(value)
  return text.length > max ? `${text.slice(0, max)}…` : text
}

const notify = (message, kind) => {
  try {
    host.notify({ kind: kind || 'info', message: clampText(message, 400) })
  } catch (err) {
    // A missing bridge must never break an action; the pane still refreshes.
  }
}

const notifyError = (error, fallback) => {
  try {
    host.notifyError(error, fallback)
  } catch (err) {
    notify(fallback, 'warning')
  }
}

const describeError = (error) => {
  if (!error) return 'unknown error'
  return error.message || String(error)
}

const DIM = { color: 'var(--ui-text-tertiary)' }
const ROW = {
  display: 'flex',
  flexDirection: 'column',
  gap: '0.25rem',
  padding: '0.5rem',
  borderBottom: '1px solid var(--ui-stroke-secondary)'
}
const ACTIONS = { display: 'flex', gap: '0.375rem', flexWrap: 'wrap', marginTop: '0.25rem' }
const BTN = {
  padding: '0.125rem 0.5rem',
  borderRadius: '0.25rem',
  border: '1px solid var(--ui-stroke-secondary)',
  color: 'var(--ui-text-secondary)',
  background: 'transparent',
  cursor: 'pointer',
  fontSize: '0.6875rem'
}
const PRE = {
  maxHeight: '14rem',
  overflow: 'auto',
  margin: '0.25rem 0 0',
  padding: '0.5rem',
  fontSize: '0.6875rem',
  whiteSpace: 'pre-wrap',
  color: 'var(--ui-text-secondary)'
}

export default {
  id: PLUGIN_ID,
  name: 'Worktree Sandbox',
  defaultEnabled: false,
  register(ctx) {
    const get = (path) => ctx.rest(path)

    const statLine = (row) =>
      `${row.changed_files || 0} file(s)  +${row.added || 0}/-${row.deleted || 0}`

    // ---- shared data hook -------------------------------------------------
    const useWorktrees = () => {
      const [state, setState] = useState({ loading: true, rows: [], error: null })
      const refresh = useCallback(async () => {
        try {
          const payload = await get('/worktrees')
          setState({ loading: false, rows: payload.worktrees || [], error: null })
        } catch (error) {
          setState({ loading: false, rows: [], error: describeError(error) })
        }
      }, [])
      useEffect(() => {
        let alive = true
        const tick = () => {
          if (alive) refresh()
        }
        tick()
        const dispose = ctx.setInterval(tick, POLL_MS)
        const disposeEvent = ctx.onEvent(UPDATED_EVENT, tick)
        return () => {
          alive = false
          dispose()
          disposeEvent()
        }
      }, [refresh])
      return { ...state, refresh }
    }

    // ---- pane -------------------------------------------------------------
    function WorktreePane() {
      const { loading, rows, error, refresh } = useWorktrees()
      const [openDiff, setOpenDiff] = useState(null)
      const [diffText, setDiffText] = useState('')
      const [busy, setBusy] = useState('')

      const withBusy = async (key, action) => {
        setBusy(key)
        try {
          await action()
        } catch (err) {
          notifyError(err, `Worktree Sandbox: ${describeError(err)}`)
        } finally {
          setBusy('')
          refresh()
        }
      }

      const showDiff = (id) =>
        withBusy(`diff:${id}`, async () => {
          if (openDiff === id) {
            setOpenDiff(null)
            return
          }
          const payload = await get(`/worktrees/${encodeURIComponent(id)}/diff`)
          setDiffText(payload.diff || '(no changes)')
          setOpenDiff(id)
        })

      const promote = (id, force) =>
        withBusy(`promote:${id}`, async () => {
          const result = await get(`/worktrees/${encodeURIComponent(id)}/promote`, {
            method: 'POST',
            body: { force: Boolean(force) }
          })
          if (result.ok === false) {
            notify(
              `Refused: ${(result.conflicts || []).map((c) => c.path).join(', ')} changed on the host. ` +
                'Use Force to overwrite (a backup is still written).',
              'warning'
            )
          } else {
            notify(`Promoted ${id}: ${(result.applied || []).length} file(s) into your checkout.`)
          }
        })

      const discard = (id) =>
        withBusy(`discard:${id}`, async () => {
          await get(`/worktrees/${encodeURIComponent(id)}`, { method: 'DELETE' })
          notify(`Discarded ${id}. Your checkout was never touched.`)
        })

      const runDemo = () =>
        withBusy('demo', async () => {
          const result = await get('/demo', { method: 'POST', body: {} })
          const winner = (result.results || []).find((r) => r.label === result.winner)
          notify(
            `Demo race: winner ${result.winner}` +
              (winner ? ` (${winner.duration_ms} ms, score ${winner.score})` : '')
          )
        })

      const header = jsxs('div', {
        style: { display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.5rem' },
        children: [
          jsx('div', { style: { fontWeight: 600 }, children: 'Worktree Sandbox' }),
          jsxs('div', {
            style: { ...DIM, fontSize: '0.6875rem' },
            children: [`${rows.length} worktree(s)`]
          }),
          jsx('div', { style: { flex: 1 } }),
          jsx('button', {
            type: 'button',
            style: BTN,
            disabled: busy === 'demo',
            onClick: runDemo,
            children: busy === 'demo' ? 'Racing…' : 'Run demo race'
          }),
          jsx('button', { type: 'button', style: BTN, onClick: refresh, children: 'Refresh' })
        ]
      })

      let body
      if (loading && rows.length === 0) {
        body = jsx('div', { style: { ...DIM, padding: '0.75rem' }, children: 'Loading worktrees…' })
      } else if (error) {
        body = jsxs('div', {
          style: { ...DIM, padding: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' },
          children: [
            jsx('div', { children: 'Worktree Sandbox backend is not reachable.' }),
            jsx('div', { children: clampText(error, 300) }),
            jsx('div', {
              children: 'Enable the plugin (hermes plugins enable worktree-sandbox) and restart the gateway.'
            })
          ]
        })
      } else if (rows.length === 0) {
        body = jsxs('div', {
          style: { ...DIM, padding: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' },
          children: [
            jsx('div', { children: 'No worktrees yet.' }),
            jsx('div', {
              children:
                'Set terminal.backend: worktree (or ask the agent to edit a project) and each task gets its own isolated worktree.'
            }),
            jsx('div', { children: 'Run the demo race above to see the arena in action.' })
          ]
        })
      } else {
        body = jsx('div', {
          style: { overflow: 'auto', flex: 1 },
          children: rows.map((row) =>
            jsxs(
              'div',
              {
                style: ROW,
                children: [
                  jsxs('div', {
                    style: { display: 'flex', gap: '0.5rem', alignItems: 'baseline' },
                    children: [
                      jsx('span', { style: { fontWeight: 500 }, children: row.worktree_id }),
                      jsx('span', {
                        style: { ...DIM, fontSize: '0.6875rem' },
                        children: row.clean ? 'clean' : 'pending changes'
                      })
                    ]
                  }),
                  jsx('div', { style: { ...DIM, fontSize: '0.6875rem' }, children: statLine(row) }),
                  jsxs('div', {
                    style: ACTIONS,
                    children: [
                      jsx('button', {
                        type: 'button',
                        style: BTN,
                        disabled: busy === `diff:${row.worktree_id}`,
                        onClick: () => showDiff(row.worktree_id),
                        children: openDiff === row.worktree_id ? 'Hide diff' : 'Diff'
                      }),
                      jsx('button', {
                        type: 'button',
                        style: BTN,
                        disabled: Boolean(busy) || row.clean,
                        onClick: () => promote(row.worktree_id, false),
                        children: 'Promote'
                      }),
                      jsx('button', {
                        type: 'button',
                        style: BTN,
                        disabled: Boolean(busy),
                        onClick: () => promote(row.worktree_id, true),
                        children: 'Force'
                      }),
                      jsx('button', {
                        type: 'button',
                        style: BTN,
                        disabled: Boolean(busy),
                        onClick: () => discard(row.worktree_id),
                        children: 'Discard'
                      })
                    ]
                  }),
                  openDiff === row.worktree_id ? jsx('pre', { style: PRE, children: diffText }) : null
                ]
              },
              row.worktree_id
            )
          )
        })
      }

      return jsxs('div', {
        style: { display: 'flex', flexDirection: 'column', height: '100%', fontSize: '0.75rem' },
        children: [header, body]
      })
    }

    // ---- status chip ------------------------------------------------------
    function StatusChip() {
      const { rows } = useWorktrees()
      const dirty = rows.filter((row) => !row.clean)
      const added = rows.reduce((sum, row) => sum + (row.added || 0), 0)
      const deleted = rows.reduce((sum, row) => sum + (row.deleted || 0), 0)
      return jsx('button', {
        type: 'button',
        title: 'Worktree Sandbox — click to open the pane',
        style: {
          padding: '0 0.25rem',
          border: 'none',
          background: 'transparent',
          cursor: 'pointer',
          fontSize: '0.6875rem',
          color: dirty.length ? 'var(--ui-text-secondary)' : 'var(--ui-text-tertiary)'
        },
        onClick: () => {
          try {
            sdk.haptic('tap')
          } catch (err) {
            // haptics are optional
          }
          notify(
            dirty.length
              ? `${dirty.length} worktree(s) pending: +${added}/-${deleted}. Open the Worktree Sandbox pane.`
              : 'No pending worktree changes.'
          )
        },
        children: rows.length
          ? dirty.length
            ? `wt ${dirty.length} · +${added}/-${deleted}`
            : `wt ${rows.length}`
          : 'wt'
      })
    }

    // ---- transcript directive --------------------------------------------
    // The agent can emit `::worktree-card{race_id="..."}` (see the plugin skill); the card reads
    // the recorded race back from the plugin's own backend.
    function WorktreeCard({ attrs }) {
      const raceId = attrs && attrs.race_id ? String(attrs.race_id) : ''
      const [race, setRace] = useState(null)
      const [error, setError] = useState(null)
      const load = useCallback(async () => {
        if (!raceId) {
          setError('missing race_id')
          return
        }
        try {
          const payload = await get(`/races/${encodeURIComponent(raceId)}`)
          setRace(payload.race || null)
        } catch (err) {
          setError(describeError(err))
        }
      }, [raceId])
      useEffect(() => {
        load()
        const dispose = ctx.onEvent(UPDATED_EVENT, load)
        return () => dispose()
      }, [load])

      if (error) {
        return jsx('div', { style: { ...DIM, fontSize: '0.6875rem' }, children: `race ${raceId}: ${error}` })
      }
      if (!race) {
        return jsx('div', { style: { ...DIM, fontSize: '0.6875rem' }, children: 'Loading race…' })
      }
      const results = (race.result && race.result.results) || []
      return jsxs('div', {
        style: { border: '1px solid var(--ui-stroke-secondary)', borderRadius: '0.375rem', padding: '0.5rem' },
        children: [
          jsxs('div', {
            style: { display: 'flex', gap: '0.5rem', alignItems: 'baseline', marginBottom: '0.25rem' },
            children: [
              jsx('span', { style: { fontWeight: 600 }, children: 'Speculative race' }),
              jsx('span', { style: { ...DIM, fontSize: '0.6875rem' }, children: clampText(race.id, 40) })
            ]
          }),
          jsx('div', {
            children: results.map((row) =>
              jsxs(
                'div',
                {
                  style: {
                    display: 'flex',
                    gap: '0.5rem',
                    fontFamily: 'monospace',
                    fontSize: '0.6875rem',
                    color: row.label === race.winner ? 'var(--ui-text-primary)' : 'var(--ui-text-tertiary)'
                  },
                  children: [
                    jsx('span', { style: { minWidth: '6rem' }, children: clampText(row.label, 24) }),
                    jsx('span', { children: row.passed ? 'PASS' : row.timed_out ? 'TIMEOUT' : 'FAIL' }),
                    jsx('span', { children: `${row.duration_ms} ms` }),
                    jsx('span', { children: `+${row.added}/-${row.deleted}` }),
                    jsx('span', { children: `score ${row.score}` })
                  ]
                },
                row.label
              )
            )
          }),
          jsx('div', {
            style: { ...DIM, fontSize: '0.6875rem', marginTop: '0.25rem' },
            children: `winner: ${race.winner || 'none'}`
          })
        ]
      })
    }

    // ---- workspace view (used by the palette command) ----------------------
    const openWorkspace = (title, render) => {
      if (typeof host.openWorkspace !== 'function') {
        notify('Open the Worktree Sandbox pane from the pane picker (this Desktop build has no workspace API).')
        return
      }
      host.openWorkspace(`${PLUGIN_ID}-arena`, { title, minWidth: '420px', render })
    }

    // ---- registrations ----------------------------------------------------
    ctx.register({ id: 'pane', area: AREA_PANES, title: 'worktrees', order: 40,
      data: { placement: 'right', width: '320px' }, render: () => jsx(WorktreePane, {}) })

    ctx.register({ id: 'chip', area: AREA_STATUS_RIGHT, order: 140, render: () => jsx(StatusChip, {}) })

    ctx.register({
      id: 'cmd-demo',
      area: AREA_PALETTE,
      data: {
        id: `${PLUGIN_ID}.demo`,
        label: 'Worktree Sandbox: run the demo race',
        keywords: ['worktree', 'sandbox', 'race', 'demo', 'git'],
        run: async () => {
          try {
            const result = await get('/demo', { method: 'POST', body: {} })
            notify(`Demo race: winner ${result.winner}`)
            ctx.emit('race.completed', { race_id: result.race_id, winner: result.winner })
          } catch (error) {
            notifyError(error, `Worktree Sandbox: ${describeError(error)}`)
          }
        }
      }
    })

    ctx.register({
      id: 'cmd-arena',
      area: AREA_PALETTE,
      data: {
        id: `${PLUGIN_ID}.arena`,
        label: 'Worktree Sandbox: open the arena',
        keywords: ['worktree', 'sandbox', 'diff', 'promote'],
        run: () => openWorkspace('Worktree Sandbox', () => jsx(WorktreePane, {}))
      }
    })

    if (typeof AREA_DIRECTIVE === 'string') {
      ctx.register({
        id: 'directive',
        area: AREA_DIRECTIVE,
        data: {
          name: 'worktree-card',
          render: ({ attrs }) => jsx(WorktreeCard, { attrs: attrs || {} })
        }
      })
    }

    ctx.registerSettingsPage?.({
      id: 'worktree-sandbox',
      title: 'Worktree Sandbox',
      icon: 'git-branch',
      order: 55,
      render: () =>
        jsxs('div', {
          style: { display: 'flex', flexDirection: 'column', gap: '0.5rem', fontSize: '0.75rem' },
          children: [
            jsx('div', { children: 'Agent settings for this plugin (verify command, limits) live in the Agent settings sub-page.' }),
            jsx('div', {
              style: DIM,
              children: 'Every command runs in an isolated Git worktree; your checkout changes only when you press Promote.'
            }),
            jsx(WorktreePane, {})
          ]
        })
    })
  }
}
