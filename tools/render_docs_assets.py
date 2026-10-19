#!/usr/bin/env python3
"""Regenerate original, accessible SVG documentation artwork (stdlib only)."""
from pathlib import Path
from html import escape

ROOT = Path(__file__).resolve().parents[1] / "docs" / "assets"
INK, MUTED, LINE = "#e8f0ff", "#a8b9d0", "#304563"
COLORS = ["#55d6be", "#65b9ff", "#a89bff", "#f4c46b", "#fa9ca5"]


def text(x, y, value, size=20, color=INK, weight=400):
    return '<text x="%s" y="%s" font-size="%s" fill="%s" font-weight="%s">%s</text>' % (x, y, size, color, weight, escape(value))


def box(x, y, w, h, fill="#14233a", stroke=LINE, radius=16):
    return '<rect x="%s" y="%s" width="%s" height="%s" rx="%s" fill="%s" stroke="%s"/>' % (x, y, w, h, radius, fill, stroke)


def arrow(x1, y1, x2, y2, color="#65b9ff", dashed=False):
    return '<path d="M%s %s L%s %s" fill="none" stroke="%s" stroke-width="3"%s marker-end="url(#arrow)"/>' % (x1, y1, x2, y2, color, ' stroke-dasharray="7 6"' if dashed else "")


def icon(kind, x, y, color, scale=1):
    paths = {
        "chip": '<rect x="14" y="14" width="36" height="36" rx="7"/><rect x="23" y="23" width="18" height="18" rx="3"/>' + ''.join('<path d="M%s 6v8 M%s 50v8 M6 %sh8 M50 %sh8"/>' % (i, i, i, i) for i in (22, 32, 42)),
        "memory": '<rect x="8" y="15" width="48" height="32" rx="5"/><path d="M16 47v8 M26 47v8 M38 47v8 M48 47v8"/>' + ''.join('<rect x="%s" y="24" width="8" height="14" rx="2"/>' % i for i in (16, 28, 40)),
        "serve": '<path d="M8 19h30 M30 10l9 9-9 9 M56 45H26 M34 36l-9 9 9 9"/><rect x="43" y="10" width="13" height="18" rx="3"/><rect x="8" y="36" width="13" height="18" rx="3"/>',
        "cluster": '<rect x="22" y="6" width="20" height="16" rx="3"/><rect x="4" y="42" width="20" height="16" rx="3"/><rect x="40" y="42" width="20" height="16" rx="3"/><path d="M32 22v11 H14v9 M32 33h18v9"/>',
        "observe": '<path d="M9 51V12 M9 51h47 M16 39l11-13 10 7 16-20"/><circle cx="27" cy="26" r="3"/><circle cx="37" cy="33" r="3"/>',
        "contract": '<rect x="14" y="7" width="36" height="50" rx="6"/><path d="M23 20h18 M23 30h18 M23 43l6 6 12-13"/>',
    }
    return '<g transform="translate(%s %s) scale(%s)" fill="none" stroke="%s" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">%s</g>' % (x, y, scale, color, paths[kind])


def save(name, title, desc, width, height, parts):
    ROOT.mkdir(parents=True, exist_ok=True)
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="%s" height="%s" viewBox="0 0 %s %s" role="img" aria-labelledby="title desc"><title id="title">%s</title><desc id="desc">%s</desc><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto-start-reverse"><path d="M0 0L8 4L0 8" fill="#65b9ff"/></marker><linearGradient id="bg" x2="1" y2="1"><stop stop-color="#101f36"/><stop offset="1" stop-color="#09111f"/></linearGradient></defs><rect width="100%%" height="100%%" rx="22" fill="url(#bg)"/><g font-family="Segoe UI, Arial, sans-serif">%s</g></svg>' % (width, height, width, height, escape(title), escape(desc), ''.join(parts))
    (ROOT / name).write_text(svg + '\n', encoding="utf-8")


def save_clean(name, title, desc, width, height, parts, background=None):
    """Compact README artwork, with explicit light and dark theme variants."""
    ROOT.mkdir(parents=True, exist_ok=True)
    backdrop = '<rect width="100%%" height="100%%" rx="12" fill="%s"/>' % background if background else ''
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="%s" height="%s" '
           'viewBox="0 0 %s %s" role="img" aria-labelledby="title desc">'
           '<title id="title">%s</title><desc id="desc">%s</desc>'
           '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">'
           '<path d="M0 0L8 4L0 8" fill="#8b96a8"/></marker></defs>%s'
           '<g font-family="Segoe UI, Arial, sans-serif">%s</g></svg>') % (
               width, height, width, height, escape(title), escape(desc), backdrop, ''.join(parts))
    (ROOT / name).write_text(svg + '\n', encoding="utf-8")


def readme_artwork():
    for theme, bg, card, ink, muted, border, accent in [
        ('light', '#ffffff', '#f6f8fa', '#1f2328', '#59636e', '#d1d9e0', '#107e72'),
        ('dark', '#0d1117', '#161b22', '#e6edf3', '#9198a1', '#30363d', '#55d6be'),
    ]:
        p = [icon('chip', 6, 9, accent, 1), text(86, 63, 'AI-RM', 64, ink, 700)]
        save_clean('wordmark-%s.svg' % theme, 'AI-RM',
                   'AI-RM project wordmark and original accelerator icon.', 320, 82, p)
        p = [box(24, 24, 1232, 108, fill=card, stroke=border, radius=10),
             text(48, 68, 'AI-RM', 28, ink, 650),
             text(1000, 65, 'INTEGRATION HUB', 14, muted, 600),
             text(48, 106, 'Resource contracts  /  Kubernetes + llm-d  /  Operations & measurements', 21, muted),
             arrow(640, 140, 640, 164, '#8b96a8'),
             box(24, 178, 1232, 162, fill=bg, stroke=border, radius=10),
             text(48, 210, 'OPTIMUS PRIME  /  ENGINE CONSOLIDATION TARGET', 14, accent, 600),
             text(48, 258, 'Inference runtime', 27, ink, 600),
             text(48, 298, 'opt_prime/  ·  PD, KV and offload integration planned', 18, muted),
             '<path d="M640 230V314" stroke="%s"/>' % border,
             text(676, 258, 'FASOP', 27, ink, 600),
             text(676, 298, 'fasop/  ·  Planning & search', 18, muted),
             text(48, 391, 'RESEARCH SCOPE', 13, muted, 600),
             text(230, 393, 'GPU  ·  FuriosaAI RNGD  ·  Rebellions ATOM  ·  CPU  ·  GB10', 20, ink)]
        save_clean('overview-%s.svg' % theme, 'AI-RM and Optimus Prime target architecture',
                   'AI-RM coordinates resource contracts, Kubernetes llm-d and operations. '
                   'Optimus Prime is the planned engine consolidation target, with opt_prime runtime '
                   'and FASOP planning in one product. Inference planning and PD/KV/offload migration '
                   'remain future work. Hardware labels describe research scope, not certified support.',
                   1280, 422, p, bg)
        p = [box(16, 16, 608, 120, fill=card, stroke=border, radius=10),
             text(40, 61, 'AI-RM', 32, ink, 650),
             text(421, 59, 'INTEGRATION HUB', 15, muted, 600),
             text(40, 97, 'Resource contracts · Kubernetes + llm-d', 22, muted),
             text(40, 124, 'Operations & measurements', 21, muted),
             arrow(320, 145, 320, 170, '#8b96a8'),
             box(16, 184, 608, 314, fill=bg, stroke=border, radius=10),
             text(40, 220, 'OPTIMUS PRIME · TARGET', 20, accent, 600),
             text(40, 266, 'Inference runtime', 30, ink, 600),
             text(40, 302, 'opt_prime/', 23, muted),
             text(40, 335, 'PD, KV & offload integration planned', 20, muted),
             '<path d="M40 358H600" stroke="%s"/>' % border,
             text(40, 404, 'FASOP', 30, ink, 600),
             text(40, 441, 'fasop/ · Planning & search', 23, muted),
             text(40, 546, 'RESEARCH SCOPE', 17, muted, 600),
             text(40, 581, 'GPU · RNGD · ATOM · CPU · GB10', 25, ink)]
        save_clean('overview-mobile-%s.svg' % theme, 'AI-RM target architecture for small screens',
                   'AI-RM integration hub above the Optimus Prime runtime and FASOP planner. '
                   'Consolidation and inference planning remain future work. Hardware labels denote research scope.',
                   640, 610, p, bg)


def main():
    readme_artwork()
    p = [text(48, 53, "AI-COMPUTING / RESEARCH & INTEGRATION", 15, COLORS[0], 600),
         text(44, 147, "AI-RM", 86, INK, 700),
         text(48, 199, "Unified resource management", 29, INK, 600),
         text(48, 238, "Optimus Prime engine integration", 24, MUTED),
         text(48, 303, "GPU  /  NPU  /  CPU  /  UNIFIED MEMORY", 16, COLORS[0], 600),
         text(48, 350, "Discover. Move. Execute. Orchestrate. Observe.", 18, MUTED)]
    for i, (label, kind) in enumerate([("GPU", "chip"), ("NPU", "chip"), ("CPU", "chip"), ("GB10", "memory")]):
        x = 785 + (i % 2) * 206
        y = 67 + (i // 2) * 140
        p += [box(x, y, 175, 112, stroke=COLORS[i]), icon(kind, x+13, y+16, COLORS[i], .8), text(x+78, y+62, label, 23, INK, 600)]
    p += [text(799, 365, "Kubernetes + llm-d", 23, INK, 600)]
    save("hero.svg", "AI-RM — unified resource management", "Research integration hub for GPU, NPU, CPU and GB10 unified-memory systems, organized in five layers on Kubernetes and llm-d.", 1280, 400, p)

    rows = [
        ("L5", "Observability & operations", "lmd-top  /  rm-bench", "Latency, throughput, power and evidence", "observe"),
        ("L4", "Cluster & planning boundary", "hetero-llm-d  /  FASOP adapter (planned)", "Gateway / EPP; planner is part of Optimus Prime", "cluster"),
        ("L3", "Unified engine", "Optimus Prime (aicomp/opt_prime)", "Inference consolidation target; npu-train workload", "serve"),
        ("L2", "Memory & transport modules", "KV transport  /  expert offload  /  duet*", "Engine modules planned; *private search workload", "memory"),
        ("L1", "Accelerator abstraction", "rm-accel", "Device discovery, capabilities and plugins", "chip"),
    ]
    p = [text(40, 51, "One integration hub. Five technical layers.", 30, INK, 600), text(40, 84, "Logical architecture • integration targets; component readiness varies", 17, MUTED)]
    for i, (layer, title, names, desc, kind) in enumerate(rows):
        y, c = 110 + i*99, COLORS[4-i]
        p += [box(32,y,1070,86), icon(kind,49,y+12,c,.85), text(124,y+34,layer,22,c,700), text(185,y+34,title,23,INK,600), text(185,y+63,desc,16,MUTED), text(620,y+49,names,18,INK,500)]
    p += [box(1120,110,128,482,fill="#182841",stroke=COLORS[0]), text(1137,154,"rm-core",22,COLORS[0],600)]
    for i,v in enumerate(["Shared", "contracts", "", "Adapters", "Metrics", "Profiles", "", "Across", "L1–L5"]):
        p += [text(1137,201+i*36,v,18,MUTED)]
    p += [text(40,638,"HARDWARE   GPU  ·  FuriosaAI RNGD  ·  Rebellions ATOM  ·  CPU  ·  GB10",19,COLORS[0],600)]
    save("architecture.svg", "AI-RM target architecture with Optimus Prime", "L1 resource discovery, L2 memory modules, L3 Optimus Prime unified engine and training workloads, L4 Kubernetes llm-d and the FASOP planner integration boundary, L5 operations. Optimus Prime and FASOP share the aicomp repository. Consolidation is planned, not implemented by this documentation change. duet remains a private optional workload.",1280,676,p)

    p=[text(40,52,"One engine boundary for heterogeneous inference",30,INK,600),text(40,85,"Target: Optimus Prime workers • NPU/backend migration and llm-d adapter remain planned",17,MUTED)]
    for x,w,title,subtitle in [(40,170,"Client","LLM request"),(267,255,"Gateway + EPP","L4 · route / place"),(580,280,"Prefill worker","Optimus Prime · target"),(923,310,"Decode worker","Optimus Prime · target")]:
        p += [box(x,135,w,105),text(x+18,177,title,23,INK,600),text(x+18,212,subtitle,17,MUTED)]
    p += [arrow(211,188,263,188),arrow(524,188,576,188),arrow(864,188,919,188),text(882,122,"KV",17,COLORS[0],600),box(580,286,653,94,stroke=COLORS[1]),text(600,322,"L2 · choose a named KV transport",22,INK,600),text(600,354,"p2p: compatible same-host devices  /  shm: host staging",17,MUTED),arrow(720,242,720,282),arrow(1076,282,1076,244),box(40,286,481,94,stroke=COLORS[0]),text(60,322,"L1 · device capabilities",22,INK,600),text(60,354,"Discovery, memory, precision and peak source",17,MUTED),box(40,431,1193,97,stroke=COLORS[4]),text(60,468,"L5 · observe and evaluate",23,COLORS[4],600),text(60,503,"Prometheus / Grafana  →  lmd-top    |    rm-bench  →  TTFT · TPOT · tok/s · SLO",20,INK),arrow(907,383,907,426,dashed=True)]
    save("request-flow.svg","Target Optimus Prime request flow","Client requests pass through Gateway and EPP to planned Optimus Prime prefill and decode workers. Existing RNGD/ATOM PD technology is a migration source. A named, supported KV transport connects stages; P2P remains same-host and hardware dependent. Integration is not implemented by this documentation change.",1280,570,p)

    p=[text(40,52,"Three memory paths. Different jobs.",30,INK,600),text(40,85,"Memory integration is workload specific; these paths are not interchangeable.",17,MUTED)]
    data=[("KV CACHE TRANSFER","hetero-npu-p2p","RNGD device memory","ATOM device memory","Same-host KV movement with completion fencing"), ("MoE EXPERT OFFLOAD","npu-offload","NPU HBM · hot experts","Host CPU / DRAM · cold experts","Partition expert execution across device and host"), ("UNIFIED-MEMORY SEARCH","duet · private / optional","CPU · graph traversal","GPU · distance calculation","GB10 shared memory for cooperative vector search")]
    for i,(label,name,a,b,desc) in enumerate(data):
        y,c=115+i*135,COLORS[i]
        p += [box(32,y,1216,119),text(52,y+30,label,14,c,700),text(52,y+65,name,24,INK,600),text(52,y+94,desc,16,MUTED),box(680,y+28,230,61,fill="#1c304b"),text(694,y+64,a,16,INK,500),arrow(916,y+58,966,y+58),box(975,y+28,251,61,fill="#1c304b"),text(989,y+64,b,16,INK,500)]
    save("memory-paths.svg","AI-RM memory paths","hetero-npu-p2p transfers KV between compatible same-host NPUs. npu-offload separates hot NPU experts and cold host CPU experts. Private optional duet combines CPU graph traversal and GPU distance computation in GB10 unified memory.",1280,550,p)

    p=[text(40,51,"From hardware to reproducible evidence",30,INK,600)]
    for i,(title,desc,kind) in enumerate([("Discover","Devices & profiles","chip"),("Connect","Contracts & adapters","contract"),("Execute","Workloads & transport","serve"),("Measure","Metrics & run context","observe")]):
        x=40+i*310
        p += [box(x,88,270,136),icon(kind,x+16,103,COLORS[i],.65),text(x+78,125,title,23,INK,600),text(x+18,192,desc,18,MUTED)]
        if i<3:p += [arrow(x+276,155,x+302,155)]
    save("research-workflow.svg","Research evidence workflow","Discover device capabilities, connect implementations through rm-core contracts, execute workloads with explicit transport selection, and record measurements with reproducible run context.",1280,262,p)
    p=[text(40,51,"AI-RM coordinates. Optimus Prime executes.",30,INK,600),text(40,85,"Target ownership • existing source repositories remain pinned during migration",17,MUTED),box(32,114,1216,82,stroke=COLORS[3]),text(52,149,"AI-RM  /  resource & cluster integration",25,COLORS[3],600),text(52,179,"rm-core contracts  ·  device inventory  ·  Kubernetes + llm-d  ·  lmd-top  ·  rm-bench",18,INK),arrow(639,201,639,236),box(32,246,1216,289,stroke=COLORS[0]),text(52,283,"OPTIMUS PRIME  /  ai-computing/aicomp",27,COLORS[0],700),text(52,315,"Current source: main  ·  planned integration branch: optimus-prime (not created here)",18,MUTED),box(52,340,556,167,fill="#1b3047"),text(73,377,"Runtime  /  opt_prime",24,INK,600),text(73,413,"PP/TP inference, prefill/decode, KV cache",18,MUTED),text(73,444,"Planned: NPU backends, PD, KV, expert offload",18,MUTED),text(73,477,"One runtime owner; modules keep explicit contracts",17,COLORS[0]),box(629,340,597,167,fill="#1b3047"),text(650,377,"Planner  /  fasop",24,INK,600),text(650,413,"Current: training cost / TP-PP-DP search",18,MUTED),text(650,444,"Planned: calibrated inference planning adapter",18,MUTED),text(650,477,"Cost estimates ≠ measured inference SLO",17,COLORS[3]),text(40,585,"MIGRATION SOURCES → ENGINE MODULES (PLANNED)",18,COLORS[1],600),box(32,605,1216,75),text(52,636,"rngd-pd  ·  hetero-npu-p2p  ·  npu-offload  ·  engine-facing rm-accel adapters",20,INK),text(52,664,"Keep source submodules until implementation, conformance and end-to-end acceptance pass.",17,MUTED),text(40,727,"EXTERNAL WORKLOADS   npu-train: training adapter  /  duet: private search workload",19,COLORS[2],600)]
    save("engine-consolidation.svg","Optimus Prime consolidation target","AI-RM owns resource, contract, Kubernetes llm-d and observation integration. Optimus Prime in aicomp owns the unified runtime at opt_prime and FASOP planning at fasop. The proposed optimus-prime branch is not created. Current training cost search is not yet an inference SLO optimizer. Existing repositories remain pinned migration sources; npu-train and private duet remain workloads.",1280,770,p)
    for i,kind in enumerate(["chip","memory","serve","cluster","observe","contract"]):
        save("icon-%s.svg"%kind,kind.capitalize(),"Original AI-RM %s icon"%kind,80,80,[icon(kind,8,8,COLORS[i%5])])
    print("Generated 18 SVG assets in docs/assets/")


if __name__ == "__main__":
    main()
