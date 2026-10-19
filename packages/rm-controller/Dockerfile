# rm-controller image (ghcr.io/ai-computing/rm-controller), used by the ai-rm umbrella chart.
#
#   docker build -t ghcr.io/ai-computing/rm-controller:dev packages/rm-controller
#   docker run --rm ghcr.io/ai-computing/rm-controller:dev --help
#
# rm-core is installed from its release tarball (no git in the slim image), then this package without
# re-resolving its git dependency.
FROM python:3.11-slim

ARG RM_CORE_REF=v0.1.1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY pyproject.toml /src/
COPY rm_controller /src/rm_controller
RUN pip install --no-cache-dir \
        "https://github.com/ai-computing/rm-core/archive/refs/tags/${RM_CORE_REF}.tar.gz" \
        pyyaml "kubernetes>=24.2.0" \
    && pip install --no-cache-dir --no-deps /src \
    && rm -rf /src \
    && rm-controller --help >/dev/null

# Reads the cluster and writes one ConfigMap through its ServiceAccount; needs no root.
USER 65534:65534
ENTRYPOINT ["rm-controller"]
