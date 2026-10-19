# AI-RM documentation

[English home](../README.md) · [한국어 문서](ko/README.md)

**A guide to the AI Semiconductor Integrated Resource Management research and integration project.** This directory is the versioned, wiki-style knowledge base. It is readable directly on GitHub and travels with every checkout; it does not depend on a separately initialized GitHub Wiki.

**Current design direction:** AI-RM coordinates resources, cluster integration and evidence; **[Optimus Prime + FASOP](engine-integration.md)** is the planned consolidated engine in `aicomp`. [Planning configuration](../config/engine-integration.yaml) records ownership and migration gates without activating a new runtime.

![AI-RM five-layer architecture](assets/architecture.svg)

## Choose a reading path

| You are… | Start with | Then explore |
|---|---|---|
| A project visitor or reviewer | [Project overview](project-overview.md) | [Research scenarios](research-scenarios.md) · [KPI map](kpi-map.md) |
| A researcher | [Architecture](architecture.md) | [Interfaces](interfaces.md) · [Component directory](components/README.md) |
| An engine implementer | [Optimus Prime consolidation](engine-integration.md) | [FASOP card](components/fasop.md) · [Engine card](components/optimus-prime.md) |
| A developer integrating a component | [Getting started](getting-started.md) | [Integration guide](integration-guide.md) · [Component contract](component-contract.md) |
| An operator | [Status and access](status.md) | [Deployment](../deploy/README.md) · [Security](security.md) |
| A documentation contributor | [Contributing](../CONTRIBUTING.md) | [Visual assets and prompts](assets/README.md) · [Glossary](glossary.md) |

## Documentation map

- **Understand:** [overview](project-overview.md), [architecture](architecture.md), [scenarios](research-scenarios.md), [glossary](glossary.md).
- **Use:** [getting started](getting-started.md), [status](status.md), [deployment](../deploy/README.md).
- **Connect:** [interfaces](interfaces.md), [integration guide](integration-guide.md), [component contract](component-contract.md), [component work cards](components/README.md).
- **Evaluate:** [KPI map and evidence](kpi-map.md).
- **Maintain:** [contributing](../CONTRIBUTING.md), [security](security.md), [asset provenance](assets/README.md).

The protocol in [rm-core](https://github.com/ai-computing/rm-core/blob/main/PROTOCOL.md) is authoritative for interface definitions. Work cards describe integration tasks, not verified completion; detailed cards are currently maintained in Korean. [Status](status.md) explains how to interpret them.
