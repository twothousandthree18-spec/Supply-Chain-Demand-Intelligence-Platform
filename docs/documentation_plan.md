# Documentation Plan

**Phase 0 — Structure defined. Content for later phases is created as each phase completes.**

## 1. Top-Level `docs/` Map

| Document | Status (Phase 0) |
|---|---|
| `architecture.md` | ✅ written |
| `dataset_strategy.md` | ✅ written |
| `database_architecture.md` | ✅ written |
| `erd.md` | ✅ written (spec) |
| `analytics_architecture.md` | ✅ written |
| `forecasting_architecture.md` | ✅ written |
| `inventory_simulation_architecture.md` | ✅ written |
| `scenario_engine.md` | ✅ written |
| `decision_engine.md` | ✅ written |
| `powerbi_architecture.md` | ✅ written |
| `design_system.md` | ✅ written |
| `web_application_architecture.md` | ✅ written |
| `testing_strategy.md` | ✅ written |

## 2. Planned Project Documentation Set (mapped to recruiter-standard sections)

| Documentation item | Planned content | Phase |
|---|---|---|
| **README.md** | Project identity, overview, structure, quick links, phase status. | 0 (stub) / maintained throughout |
| **Business Problem** | The question, context, why it matters. | 1 |
| **Dataset** | M5 description, files, provenance. | 1 |
| **Data Dictionary** | Every field across tables: name, type, meaning, source (observed/derived/simulated). | 1 |
| **Architecture** | Layered pipeline (exists — refined). | 0/1 |
| **ERD** | Diagram + relationship spec (exists as spec — rendered later). | 1 |
| **Analytical Methodology** | How each KPI/analysis is computed. | 2 |
| **Forecasting Methodology** | Models, validation, accuracy, honesty rules. | 2 |
| **Inventory Assumptions** | Full assumption set + rationale. | 3 |
| **Scenario Methodology** | Scenario definitions, inputs, outputs. | 3 |
| **KPI Definitions** | Canonical one-per-KPI definitions reference. | 2 |
| **Testing** | Strategy (exists) + actual test status/results. | throughout |
| **Limitations** | Explicit constraints incl. no-inventory-in-M5. | 2 |
| **Reproducibility** | Environment, commands, seeds, pins. | throughout |
| **Deployment / Presentation** | How dashboards/website are produced and served. | 4 |
| **Phase 0 Completion Report** | This phase's environment/structure/status summary. | 0 |

## 3. House Style

- Official project name and subtitle used verbatim in all titles/metadata.
- Every doc: version + phase notation.
- Every analytical/simulated claim carries provenance classification.
