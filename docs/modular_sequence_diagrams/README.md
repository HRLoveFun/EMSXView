# Modular Sequence Diagrams

## Overview

Sequence diagrams for the main module interaction flows:
- `01-execution-initial-load` — Order blotter and position loading
- `02-execution-modify-order` — Order modification flow
- `03-execution-route-management` — Route management flow
- `04-costview-daily-pipeline` — CostView daily pipeline
- `05-costview-bdib-branch` — CostView BDIB branch flow

## Files

- `mermaid/*.mmd` — Mermaid source files (editable)
- `images/*.svg` — Rendered SVGs (viewable in docs)

## How to Regenerate SVGs

Prerequisites: Node.js, mermaid-cli

```bash
# Install once
npm install -g @mermaid-js/mermaid-cli

# Regenerate all SVGs
cd docs/modular_sequence_diagrams/mermaid
npx -p @mermaid-js/mermaid-cli mmdc \
  -i 01-execution-initial-load.mmd \
  -o ../images/01-execution-initial-load.svg \
  -c puppeteer-config.json \
  -C mermaid-fonts.css

# Repeat for each file, or use a loop:
for f in *.mmd; do
  npx -p @mermaid-js/mermaid-cli mmdc \
    -i "$f" \
    -o "../images/${f%.mmd}.svg" \
    -c puppeteer-config.json \
    -C mermaid-fonts.css
done
```

> Note: `puppeteer-config.json` passes `--no-sandbox` for WSL/Linux environments.  
> `mermaid-fonts.css` ensures CJK font support in rendered SVGs.
