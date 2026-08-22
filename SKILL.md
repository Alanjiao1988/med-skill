# Pediatric MCD / Nephrotic Syndrome Monthly Evidence Surveillance

## Purpose

Run a monthly evidence surveillance workflow focused on pediatric Minimal Change Disease (MCD) and clinically overlapping childhood nephrotic syndrome phenotypes, especially SSNS, FRNS, and SDNS. Produce a concise Chinese-language evidence brief for downstream delivery by the host application.

## Core workflow

1. Search recent literature using a 45-60 day rolling window.
2. Search all six surveillance tracks: mechanism, treatment, biomarkers, natural history/safety, guidelines/consensus, and clinical trials.
3. Deduplicate against persistent state using PMID, DOI, trial registry ID, and canonical title where necessary.
4. Normalize study population and disease phenotype before interpreting findings.
5. Grade evidence strength independently from novelty and patient relevance.
6. Compare each material finding with the current evidence baseline.
7. Produce a monthly delta report, not a generic literature summary.
8. Export the brief in Markdown and email-ready text/HTML fields. The host application is responsible for delivery.

## Hard constraints

1. Never equate SSNS with biopsy-confirmed MCD.
2. Never extrapolate adult evidence to children without an explicit applicability label.
3. Never present animal, organoid, in-vitro, omics, or other mechanistic evidence as established clinical efficacy.
4. Never convert association into causation.
5. A single new study must not automatically override replicated evidence, systematic review, or guideline consensus.
6. Every material study must include both `what_this_changes` and `what_this_does_not_prove`.
7. Evidence strength, novelty, and patient relevance are separate dimensions and must be scored separately.
8. Do not make individualized treatment decisions. Identify practice-relevant evidence and questions for clinician discussion.

## Surveillance tracks

### A. Mechanisms
Focus on podocyte biology, slit diaphragm, nephrin/anti-nephrin, NEPH1, podocin, B-cell/T-cell biology, complement, circulating factors, autoimmunity, permeability mechanisms, and foot-process effacement.

### B. Treatment
Track glucocorticoid strategies, rituximab, mycophenolate mofetil, tacrolimus, cyclosporine, levamisole, cyclophosphamide, ofatumumab, obinutuzumab, and emerging steroid-sparing strategies.

### C. Biomarkers and precision phenotyping
Track diagnostic, prognostic, and predictive biomarkers. Keep these three functions distinct.

### D. Natural history and safety
Track relapse, remission, transition to adolescence/adulthood, CKD risk, growth, bone health, infection, hypertension, obesity, cataract, steroid toxicity, immunosuppressant toxicity, and quality of life.

### E. Guidelines and consensus
Track KDIGO, IPNA, ESPN/ERA and other major pediatric nephrology guidance or consensus updates.

### F. Clinical trials
Track newly registered, recruiting, completed, terminated, protocol-changed, or results-posted trials relevant to pediatric nephrotic syndrome/MCD.

## Output language

Final monthly brief: Simplified Chinese. Keep important medical terminology in English parentheses where useful.

## Delivery contract

The host AI application or automation should deliver the final monthly brief to:

`alanjiao@microsoft.com`

This Skill itself does not assume Gmail, Outlook, SMTP, or any specific mail provider.
