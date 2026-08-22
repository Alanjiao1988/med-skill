# med-skill

Living evidence surveillance for pediatric nephrotic syndrome with a focus on Minimal Change Disease (MCD), steroid-sensitive nephrotic syndrome (SSNS), frequently relapsing nephrotic syndrome (FRNS), and steroid-dependent nephrotic syndrome (SDNS).

## Goal

Produce a monthly Chinese-language academic brief covering mechanisms, treatment, biomarkers, natural history, guidelines, and clinical trials. The host AI application or workflow is responsible for scheduling and delivery to `alanjiao@microsoft.com`.

## Design principles

- Do not equate SSNS with biopsy-confirmed MCD.
- Separate pediatric from adult evidence.
- Separate mechanistic evidence from clinical evidence.
- Separate scientific importance from patient-specific relevance.
- Track monthly evidence deltas rather than generating a fresh generic review each time.
- Use rolling search windows with persistent PMID/trial deduplication.
- Explicitly state what each study does and does not prove.

This repository is intended for research and evidence-surveillance use, not as a substitute for clinical care.
