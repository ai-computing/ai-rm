# ai-rm umbrella commands. See README.md.
PY ?= python3
AIRM = $(PY) tools/airm.py
LAYER ?=
CLUSTER ?= local
LAYER_ARG = $(if $(LAYER),--layer $(LAYER),)
DRY = $(if $(DRY_RUN),--dry-run,)

.PHONY: init list doctor setup test deploy check bump chart up-sim e2e-sim down-sim

init:            ## fetch all component submodules (needs ai-computing org access)
	git submodule update --init

list:            ## components, layers, versions, deployability
	$(AIRM) list $(LAYER_ARG)

doctor:          ## prerequisites and missing pieces
	$(AIRM) doctor

setup: init      ## install components (LAYER=l2-memory to limit)
	$(AIRM) setup $(LAYER_ARG) $(COMPONENTS)

test:            ## quick tests that need no accelerator
	$(AIRM) test $(LAYER_ARG) $(COMPONENTS)

deploy:          ## kubectl apply component manifests (CLUSTER=local DRY_RUN=1)
	$(AIRM) deploy --cluster $(CLUSTER) $(DRY) $(LAYER_ARG) $(COMPONENTS)

check:           ## scan ai-rm and fetched components for IPs, tokens, keys
	$(AIRM) check

bump:            ## move a component to its latest commit: make bump COMPONENT=lmd-top
	$(AIRM) bump $(COMPONENT)

chart:           ## helm lint + template of the umbrella chart (needs the rm-accel submodule)
	helm dependency update charts/ai-rm
	helm lint charts/ai-rm
	helm lint charts/ai-rm -f charts/ai-rm/ci/sim-values.yaml
	helm template airm charts/ai-rm -f charts/ai-rm/ci/sim-values.yaml > /dev/null

up-sim:          ## kind cluster airm-sim: sim accelerators, rm-controller, charts/ai-rm (docker, kind, kubectl, helm)
	$(AIRM) up-sim

e2e-sim:         ## placement + rm-bench pd-smoke on the sim cluster (NO_CLUSTER=1: in-process, no kind)
	$(AIRM) e2e-sim $(if $(NO_CLUSTER),--no-cluster,)

down-sim:        ## delete the kind cluster
	$(AIRM) down-sim
