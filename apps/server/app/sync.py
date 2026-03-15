"""
Client Sync Protocol — Slave Logic (Section 8).

Implements the 6 sync scenarios per grid:
  1. Late Join (≥2 rows executed, client has 0)        → SKIP/WAIT
  2. Fresh Join (exactly 1 row executed, client has 0)  → execute Row 0
  3. Catchup (client < grid executed rows)              → send ONE missing row
  4. Session Mismatch (old session trades)              → CLOSE_ALL stale
  5. Grid OFF with orphan trades                        → CLOSE_ALL
  6. In Sync                                            → no action

Blueprint references:
  - Section 8.1–8.8 : Full sync protocol
  - Section 11.2    : POST /api/client-ping endpoint logic
  - Section 14.4    : Ignore unknown comments
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from app.models import (
    GRID_IDS,
    GridConfig,
    GridRuntime,
    Position,
    SyncAction,
    TierState,
)

logger = logging.getLogger("elastic_dca.sync")

# Comment regex: matches our grid trade comments (Section 14.4)
# Format: {GRID_ID}_{8_hex}_{row_index}
COMMENT_REGEX = re.compile(r"^(B[12]|S[12])_[0-9a-fA-F]{8}_(\d+)$")


def parse_comment(comment: str) -> Optional[tuple[str, str, int]]:
    """
    Parse a trade comment into (grid_id, session_id, row_index).
    Returns None if the comment doesn't match expectations.

    Comment format: "B1_a1b2c3d4_0"
      → grid_id="B1", session_id="B1_a1b2c3d4", row_index=0
    """
    m = COMMENT_REGEX.match(comment)
    if not m:
        return None
    grid_id = m.group(1)
    row_index = int(m.group(2))
    # session_id is everything before the last underscore+index
    # e.g. "B1_a1b2c3d4_0" → session_id = "B1_a1b2c3d4"
    last_underscore = comment.rfind("_")
    session_id = comment[:last_underscore]
    return grid_id, session_id, row_index


def compute_sync_actions(
    tier_state: TierState,
    client_positions: list[Position],
) -> list[SyncAction]:
    """
    Core sync logic (Section 8.4): For each of the 4 grids, compare client
    positions against the grid's virtual execution state and produce actions.

    Returns a sorted list of actions: CLOSE_ALL first, then BUY/SELL (Section 8.7).
    """
    # Step 1: Categorize client positions by grid_id and session_id
    # positions_by_grid[grid_id][session_id] = [row_indices...]
    positions_by_grid: dict[str, dict[str, list[int]]] = {gid: {} for gid in GRID_IDS}
    # Also keep all session IDs per grid (for stale detection)
    all_sessions_per_grid: dict[str, set[str]] = {gid: set() for gid in GRID_IDS}

    for pos in client_positions:
        parsed = parse_comment(pos.comment)
        if parsed is None:
            # Section 14.4: Ignore positions with unknown comments
            continue
        grid_id, session_id, row_index = parsed
        if grid_id not in positions_by_grid:
            continue
        all_sessions_per_grid[grid_id].add(session_id)
        if session_id not in positions_by_grid[grid_id]:
            positions_by_grid[grid_id][session_id] = []
        positions_by_grid[grid_id][session_id].append(row_index)

    close_actions: list[SyncAction] = []
    trade_actions: list[SyncAction] = []

    for grid_id in GRID_IDS:
        config: GridConfig = tier_state.configs.get(grid_id)
        runtime: GridRuntime = tier_state.runtimes.get(grid_id)
        if not config or not runtime:
            continue

        current_session = runtime.session_id  # e.g. "B1_a1b2c3d4" or ""
        grid_on = config.on

        client_sessions = all_sessions_per_grid[grid_id]

        # ── Scenario 5: Grid OFF with orphan trades ──────────────────────
        if not grid_on or not current_session:
            # Any client positions for this grid are orphans
            for orphan_sid in client_sessions:
                close_actions.append(SyncAction(
                    action="CLOSE_ALL",
                    comment=orphan_sid,
                ))
            continue

        # ── Scenario 4: Session Mismatch (stale sessions) ────────────────
        stale_sessions = client_sessions - {current_session}
        for stale_sid in stale_sessions:
            close_actions.append(SyncAction(
                action="CLOSE_ALL",
                comment=stale_sid,
            ))

        # ── Now evaluate current session ─────────────────────────────────
        # Count executed rows in master grid
        executed_rows = [r for r in config.rows if r.executed]
        executed_count = len(executed_rows)

        if executed_count == 0:
            # Grid is ON but no rows executed yet (waiting for limit, etc.)
            continue

        # Client's row indices for the CURRENT session
        client_row_indices = set(
            positions_by_grid[grid_id].get(current_session, [])
        )
        client_count = len(client_row_indices)

        # ── Scenario 1: Late Join ────────────────────────────────────────
        if executed_count >= 2 and client_count == 0:
            # Skip — client missed safe entry window
            logger.debug(
                "Grid %s: Late join (executed=%d, client=0). Skipping.",
                grid_id, executed_count,
            )
            continue

        # ── Scenario 2: Fresh Join ───────────────────────────────────────
        if executed_count == 1 and client_count == 0:
            row_0 = executed_rows[0]
            action_type = "BUY" if grid_id.startswith("B") else "SELL"
            trade_actions.append(SyncAction(
                action=action_type,
                volume=row_0.lots,
                comment=f"{current_session}_{row_0.index}",
            ))
            logger.debug("Grid %s: Fresh join → %s row %d", grid_id, action_type, row_0.index)
            continue

        # ── Scenario 3: Catchup ──────────────────────────────────────────
        if client_count < executed_count:
            # Find the first missing row (one at a time per ping)
            for row in executed_rows:
                if row.index not in client_row_indices:
                    action_type = "BUY" if grid_id.startswith("B") else "SELL"
                    trade_actions.append(SyncAction(
                        action=action_type,
                        volume=row.lots,
                        comment=f"{current_session}_{row.index}",
                    ))
                    logger.debug(
                        "Grid %s: Catchup → %s row %d",
                        grid_id, action_type, row.index,
                    )
                    break  # Only ONE action per grid per ping (Section 8.4)
            continue

        # ── Scenario 6: In Sync ──────────────────────────────────────────
        # client_count >= executed_count → nothing to do
        logger.debug("Grid %s: In sync (executed=%d, client=%d)", grid_id, executed_count, client_count)

    # Section 8.7: CLOSE_ALL first, then BUY/SELL
    return close_actions + trade_actions


def find_tier_for_balance(
    tier_states: dict[int, TierState],
    balance: float,
) -> Optional[TierState]:
    """
    Section 8.3: Find tier where min_balance <= balance < max_balance.
    Returns None if no tier matches.
    """
    for ts in tier_states.values():
        if not ts.tier.is_active:
            continue
        if ts.tier.min_balance <= balance < ts.tier.max_balance:
            return ts
    return None


def client_has_active_session_trades(
    client_positions: list[Position],
    tier_state: TierState,
) -> bool:
    """
    Section 8.3: Check if client has any positions with comments matching
    any CURRENT active session in their assigned tier.
    Used for tier locking — if True, tier cannot be re-evaluated.
    """
    for pos in client_positions:
        parsed = parse_comment(pos.comment)
        if parsed is None:
            continue
        grid_id, session_id, _ = parsed
        if grid_id not in tier_state.runtimes:
            continue
        runtime = tier_state.runtimes[grid_id]
        if runtime.session_id and runtime.session_id == session_id:
            return True
    return False
