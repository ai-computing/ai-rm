# ai-rm umbrella commands. See README.md.
PY ?= python3
AIRM = $(PY) tools/airm.py
LAYER ?=
CLUSTER ?= local
LAYER_ARG = $(if $(LAYER),--layer $(LAYER),)
DRY = $(if $(DRY_RUN),--dry-run,)

.PHONY: init list doctor setup test deploy check bump

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
