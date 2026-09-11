# Mobile Repair AI Pro

Professional evidence-driven mobile repair diagnosis assistant.

## Current build
- Structured device and fault intake
- Power-supply/current-draw pattern analysis
- Resistance/diode/rail measurements
- Evidence-based ranked hypotheses
- Next-measurement guidance
- Repair notes and case history
- Local browser storage
- Optional server AI endpoint

## Run

```bash
python3 app.py
```

Open `http://127.0.0.1:8000`.

The diagnostic engine works without an external AI key. The optional AI endpoint is disabled unless `OPENAI_API_KEY` is configured on the server.

## Safety

The assistant is decision support. It should never recommend blind component replacement when measurements are insufficient. Always validate against the exact board revision and schematic/boardview before repair.