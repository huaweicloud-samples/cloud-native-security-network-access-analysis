# One-command deploy for the VPC network access analyzer.
#
# 1) Build the three FunctionGraph packages (SDK + engine) into infra/build/.
# 2) terraform apply the infra/ stack.
#
# Usage:
#   export HW_ACCESS_KEY=... HW_SECRET_KEY=... HW_REGION_NAME=cn-north-4
#   make deploy
#
# Optional: real VPC IDs for the cross-VPC demo scope (omit -> scope keeps its
# REPLACE_VPC_*_ID placeholder and yields 0 findings):
#   make deploy VPCA_ID=xxxxxxxx-.... VPCB_ID=yyyyyyyy-....

PYTHON ?= python3
TF     ?= terraform

.PHONY: build apply deploy

build:
	$(PYTHON) scripts/build_packages.py

apply:
	cd infra && $(TF) apply -auto-approve \
		-var="hw_access_key=$(HW_ACCESS_KEY)" \
		-var="hw_secret_key=$(HW_SECRET_KEY)" \
		-var="vpc_a_id=$(VPCA_ID)" \
		-var="vpc_b_id=$(VPCB_ID)"

deploy: build apply
