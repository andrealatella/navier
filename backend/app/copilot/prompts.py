"""System prompt, reply schema and content builders for the co-pilot."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field


class CopilotReply(BaseModel):
    """What Gemini must return, every time."""

    reply: str = Field(description="Risposta in italiano, 2-3 frasi al massimo.")
    urgency: Literal["info", "caution", "warning"] = "info"
    speak: bool = True
    tts_text: str = Field(
        default="",
        description="Testo per la voce, <= 200 caratteri, ottimizzato per la lettura ad alta voce.",
    )


class OutlookExtract(BaseModel):
    """Structured read of the PRETEMP convective-outlook map image."""

    level: int = Field(ge=0, le=3, description="Livello di rischio massimo 0-3 sulla mappa.")
    zones: list[str] = Field(
        default_factory=list,
        description="Regioni/aree italiane interessate dal rischio più alto (nomi brevi).",
    )
    summary: str = Field(
        default="", description="Sintesi in una frase italiana del quadro previsto."
    )


SYSTEM_PROMPT = """\
Sei il co-pilota di un equipaggio di storm chasing in Italia. Parli italiano,
conciso e concreto: massimo 2-3 frasi, pensate per essere lette a voce alta
mentre si è in macchina. Usa i punti cardinali (N, NE, E, SE, S, SO, O, NO) e i
chilometri.

REGOLE NON NEGOZIABILI:
1. La sicurezza viene prima della riuscita della caccia, sempre. Non suggerire
   MAI di entrare nel nucleo di una cella, attraversare strade allagate o
   sottopassi, fermarsi in zone esposte con fulmini vicini o "battere sul tempo"
   la grandine. Posizionamento corretto: fuori dalla traiettoria del nucleo,
   tipicamente sul fianco della cella, a distanza di sicurezza (>= 5-10 km dai
   nuclei grandinigeni).
2. Usa SOLO i dati presenti nello snapshot JSON. Se un dato non c'è, dillo ("non
   ho dati freschi sul radar"). Non inventare numeri, distanze o condizioni.
3. Se data_age_s supera i 600 secondi per il radar o i 120 per i fulmini,
   premetti che i dati sono vecchi.
4. Se l'operatore chiede qualcosa di pericoloso, rifiuta con calma e proponi
   l'alternativa sicura più vicina al suo obiettivo.
5. Chi guida non interagisce con te: rivolgiti all'operatore/navigatore.
6. Non generi tu gli allarmi di sicurezza: quelli sono deterministici. Tu li
   spieghi e li contestualizzi.
7. Il flag `possible_supercell` su una cella è un'EURISTICA, non una certezza:
   dice solo che la cella è longeva, intensa, molto elettrica e che il suo moto
   devia di `deviazione_flusso_deg` gradi dal flusso medio in quota (segno +
   = devia a destra). Non abbiamo il radar Doppler: nessuno ha osservato una
   rotazione. Parlane sempre al condizionale ("potrebbe essere una supercella",
   "ha un comportamento da supercella"), mai come un fatto accertato, e non
   dedurne mai la presenza di un tornado.

Rispondi SEMPRE e SOLO nello schema JSON richiesto: {reply, urgency, speak,
tts_text}. `tts_text` è una versione breve di `reply` adatta alla voce; se non
c'è nulla da dire ad alta voce, metti speak=false.\
"""


def _snapshot_block(snapshot: dict) -> str:
    """Compact JSON block the model reads as ground truth."""
    return "SNAPSHOT:\n" + json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))


def chat_contents(
    snapshot: dict, question: str, history: list[tuple[str, str]] | None = None
) -> str:
    """Build the user turn for an operator question."""
    parts: list[str] = []
    if history:
        lines = [f"{'Operatore' if r == 'user' else 'Tu'}: {t}" for r, t in history]
        parts.append("CONVERSAZIONE RECENTE (solo per contesto):\n" + "\n".join(lines))
    parts.append(_snapshot_block(snapshot))
    parts.append(f"DOMANDA OPERATORE: {question.strip()}")
    return "\n\n".join(parts)


def alert_contents(snapshot: dict, rule_id: str, priority: int, message: str) -> str:
    """Build the user turn asking the model to contextualise a fired safety alert."""
    return (
        f"{_snapshot_block(snapshot)}\n\n"
        f"È appena scattato un alert di sicurezza deterministico "
        f'(regola {rule_id}, priorità P{priority}): "{message}".\n'
        "Spiega in una frase all'operatore cosa comporta e cosa conviene fare, "
        "coerente con l'alert (non contraddirlo, non sminuirlo)."
    )


def proactive_contents(snapshot: dict) -> str:
    """Build the user turn for a periodic proactive comment (ticker)."""
    return (
        f"{_snapshot_block(snapshot)}\n\n"
        "Sei nel commento proattivo periodico. Se c'è uno sviluppo rilevante "
        "(una cella che si intensifica, un rischio che cresce, un consiglio di "
        "posizionamento utile) dillo in una frase. Se non c'è nulla di nuovo o "
        "utile da segnalare, metti speak=false e un reply brevissimo."
    )


OUTLOOK_VISION_PROMPT = (
    "Questa è la mappa PRETEMP di previsione dei temporali per l'Italia di oggi. "
    "Leggi il livello di rischio massimo indicato (scala 0-3, dove 0 = nessuno, "
    "1 = basso, 2 = moderato, 3 = alto) e le regioni o aree italiane interessate "
    "dal livello più alto. Rispondi SOLO nello schema JSON richiesto "
    "{level, zones, summary}. Se la mappa non è leggibile, metti level=0 e "
    "zones vuoto."
)
