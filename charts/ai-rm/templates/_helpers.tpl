{{- define "ai-rm.controller" -}}
{{- printf "%s-rm-controller" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "ai-rm.labels" -}}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/part-of: ai-rm
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{- define "ai-rm.controllerSelector" -}}
app.kubernetes.io/name: rm-controller
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "ai-rm.placementNamespace" -}}
{{- default .Release.Namespace .Values.placementNamespace -}}
{{- end -}}

{{/* rm-controller spec (YAML): the pools, and the namespace of airm-placement. */}}
{{- define "ai-rm.controllerSpec" -}}
{{- if not .Values.controller.pools }}
{{- fail "controller.pools must list at least one pool" }}
{{- end }}
{{- toYaml (dict "namespace" (include "ai-rm.placementNamespace" .) "pools" .Values.controller.pools) }}
{{- end -}}
