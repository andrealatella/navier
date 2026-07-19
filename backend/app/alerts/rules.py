"""Deterministic alert rules. The safety layer, never the LLM."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..config import Settings
from ..models import CellSnapshot
from ..processing.geo import compass_it
from ..processing.world import WorldState


@dataclass
class Draft:
    """What a firing rule wants to say - the engine wraps it into an Alert."""

    priority: Literal[1, 2, 3]
    title: str
    message: str
    tts_text: str
    geometry: dict | None = None
    subject: str = ""


class Rule:
    """Base rule: override `activate` (+ optional `still_active`)."""

    rule_id: str = "base"
    priority: Literal[1, 2, 3] = 3

    def __init__(self, settings: Settings) -> None:
        self.s = settings

    def activate(self, ws: WorldState) -> Draft | None:
        """Return a Draft when the activation condition is met, else None."""
        raise NotImplementedError

    def still_active(self, ws: WorldState) -> Draft | None:
        """While active, whether the alert persists (looser than activation)."""
        return self.activate(ws)


def _pt(lon: float, lat: float) -> dict:
    return {"type": "Point", "coordinates": [lon, lat]}


def _strong_cells(ws: WorldState, min_dbz: float) -> list[CellSnapshot]:
    return [c for c in ws.cells if c.max_dbz >= min_dbz]


class LightningNear(Rule):
    rule_id = "LIGHTNING_NEAR"
    priority = 1

    def activate(self, ws: WorldState) -> Draft | None:
        d = ws.nearest_strike_km
        if d is None or d > self.s.lightning_near_km:
            return None
        return self._draft(ws, d)

    def still_active(self, ws: WorldState) -> Draft | None:
        d = ws.nearest_strike_km
        if d is None or d > self.s.lightning_near_off_km:
            return None
        return self._draft(ws, d)

    def _draft(self, ws: WorldState, d: float) -> Draft:
        geom = _pt(ws.user.lon, ws.user.lat) if ws.user else None
        return Draft(
            priority=1,
            title="Fulmini nelle vicinanze",
            message=f"Fulmini a circa {d:.0f} km. Resta in auto, non sostare sotto "
            "alberi o tralicci.",
            tts_text="Fulmini nelle vicinanze. Resta in auto.",
            geometry=geom,
            subject="user",
        )


class CellInbound(Rule):
    rule_id = "CELL_INBOUND"
    priority = 1

    def _pick(self, ws: WorldState, min_sev: int, max_eta: float) -> CellSnapshot | None:
        cands = [
            c
            for c in ws.cells
            if c.severity >= min_sev and c.eta_user_min is not None and c.eta_user_min <= max_eta
        ]
        return max(cands, key=lambda c: c.severity) if cands else None

    def activate(self, ws: WorldState) -> Draft | None:
        c = self._pick(ws, self.s.cell_inbound_sev, self.s.cell_inbound_eta_min)
        return self._draft(c) if c else None

    def still_active(self, ws: WorldState) -> Draft | None:
        c = self._pick(ws, self.s.cell_inbound_off_sev, self.s.cell_inbound_eta_min * 1.3)
        return self._draft(c) if c else None

    def _draft(self, c: CellSnapshot) -> Draft:
        eta = c.eta_user_min
        fuga = compass_it((c.motion.bearing_deg - 90) % 360) if c.motion else "un lato riparato"
        return Draft(
            priority=1,
            title=f"Cella {c.id} in arrivo",
            message=f"La cella {c.id} è in rotta su di te, arrivo stimato {eta:.0f} minuti. "
            f"Valuta di spostarti verso {fuga}, fuori dalla traiettoria.",
            tts_text=f"Cella {c.id} in arrivo tra {eta:.0f} minuti. Spostati verso {fuga}.",
            geometry=_pt(*c.centroid),
            subject=f"cell{c.id}",
        )


class HailRisk(Rule):
    rule_id = "HAIL_RISK"
    priority = 2

    def _pick(self, ws: WorldState) -> CellSnapshot | None:
        if ws.user is None:
            return None
        from ..processing.geo import haversine_km

        best = None
        for c in _strong_cells(ws, self.s.hail_dbz_p2):
            cape_val = c.cape if c.cape is not None else ws.cape
            confirmed = (
                "lightning_jump" in c.flags
                or (cape_val is not None and cape_val > self.s.hail_cape_min)
                or (c.poh is not None and c.poh >= self.s.hail_poh_min)
            )
            if not confirmed:
                continue
            if haversine_km(ws.user.lon, ws.user.lat, *c.centroid) > self.s.alert_zone_km:
                continue
            if best is None or c.max_dbz > best.max_dbz:
                best = c
        return best

    def activate(self, ws: WorldState) -> Draft | None:
        c = self._pick(ws)
        if c is None:
            return None
        p1 = c.max_dbz >= self.s.hail_dbz_p1
        poh_txt = f", POH {c.poh * 100:.0f}%" if c.poh is not None else ""
        return Draft(
            priority=1 if p1 else 2,
            title=f"Rischio grandine cella {c.id}",
            message=f"Rischio grandine grossa nella cella {c.id} ({c.max_dbz:.0f} dBZ{poh_txt}). "
            "Mantieniti ad almeno 5-10 km dal nucleo e fuori dalla sua traiettoria.",
            tts_text=f"Rischio grandine nella cella {c.id}. Tieniti lontano dal nucleo.",
            geometry=_pt(*c.centroid),
            subject=f"cell{c.id}",
        )


class FlashFlood(Rule):
    rule_id = "FLASH_FLOOD"
    priority = 1

    def activate(self, ws: WorldState) -> Draft | None:
        sri_hit = ws.local_sri_mmh is not None and ws.local_sri_mmh >= self.s.flash_flood_sri_mmh
        allerta_hit = ws.dpc_alert_level in {"arancione", "rosso"}
        if not (sri_hit or allerta_hit):
            return None
        geom = _pt(ws.user.lon, ws.user.lat) if ws.user else None
        return Draft(
            priority=1,
            title="Rischio nubifragio",
            message="Rischio nubifragio e allagamenti in zona. Evita sottopassi e guadi, "
            "non attraversare acqua sulla strada.",
            tts_text="Rischio nubifragio. Evita sottopassi e strade allagate.",
            geometry=geom,
            subject="user",
        )


class LightningJump(Rule):
    rule_id = "LIGHTNING_JUMP"
    priority = 2

    def activate(self, ws: WorldState) -> Draft | None:
        from ..processing.geo import haversine_km

        for c in ws.cells:
            if "lightning_jump" not in c.flags:
                continue
            if ws.user is not None and (
                haversine_km(ws.user.lon, ws.user.lat, *c.centroid) > self.s.lightning_jump_range_km
            ):
                continue
            return Draft(
                priority=2,
                title=f"Cella {c.id} in intensificazione",
                message=f"La cella {c.id} si sta intensificando rapidamente: "
                "tasso di fulminazione raddoppiato.",
                tts_text=f"La cella {c.id} si sta intensificando rapidamente.",
                geometry=_pt(*c.centroid),
                subject=f"cell{c.id}",
            )
        return None


class DataStale(Rule):
    rule_id = "DATA_STALE"
    priority = 2

    def activate(self, ws: WorldState) -> Draft | None:
        stale: list[str] = []
        if ws.radar_age_s is not None and ws.radar_age_s > self.s.data_stale_radar_s:
            stale.append(f"radar {ws.radar_age_s / 60:.0f} min")
        if ws.lightning_age_s is not None and ws.lightning_age_s > self.s.data_stale_lightning_s:
            stale.append(f"fulmini {ws.lightning_age_s / 60:.0f} min")
        if not stale:
            return None
        which = " e ".join(stale)
        return Draft(
            priority=2,
            title="Dati non aggiornati",
            message=f"Attenzione: dati vecchi ({which}). La mappa potrebbe non riflettere "
            "la situazione reale.",
            tts_text=f"Attenzione, dati non aggiornati: {which}.",
            subject="stale",
        )


class NewStrongCell(Rule):
    rule_id = "NEW_STRONG_CELL"
    priority = 3

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._announced: set[int] = set()

    def activate(self, ws: WorldState) -> Draft | None:
        from ..processing.geo import haversine_km

        present = {c.id for c in ws.cells}
        self._announced &= present
        for c in ws.cells:
            if c.id in self._announced or c.severity < self.s.new_strong_sev:
                continue
            if ws.user is not None and (
                haversine_km(ws.user.lon, ws.user.lat, *c.centroid) > self.s.new_strong_km
            ):
                continue
            self._announced.add(c.id)
            return Draft(
                priority=3,
                title=f"Nuova cella forte {c.id}",
                message=f"Nuova cella {c.id} con severità {c.severity} ({c.max_dbz:.0f} dBZ).",
                tts_text=f"Nuova cella forte, la {c.id}.",
                geometry=_pt(*c.centroid),
                subject=f"cell{c.id}",
            )
        return None


class CellWeakening(Rule):
    rule_id = "CELL_WEAKENING"
    priority = 3

    def activate(self, ws: WorldState) -> Draft | None:
        if ws.target_cell_id is None or ws.target_severity_drop is None:
            return None
        if ws.target_severity_drop < self.s.weakening_drop_pct:
            return None
        c = ws.cell(ws.target_cell_id)
        alt = ""
        if c is not None:
            others = [o for o in ws.cells if o.id != c.id]
            if others:
                best = max(others, key=lambda o: o.severity)
                alt = f" Guarda la cella {best.id}."
        return Draft(
            priority=3,
            title="Il target sta indebolendo",
            message=f"La cella target sta perdendo intensità.{alt}",
            tts_text=f"Il target sta morendo.{alt}",
            subject=f"target{ws.target_cell_id}",
        )


def default_rules(settings: Settings) -> list[Rule]:
    """The full rule set, most-severe first."""
    return [
        LightningNear(settings),
        CellInbound(settings),
        HailRisk(settings),
        FlashFlood(settings),
        LightningJump(settings),
        DataStale(settings),
        NewStrongCell(settings),
        CellWeakening(settings),
    ]
