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

{{/* Keep the CLI's apply mode and its namespace-scoped RBAC in sync, including old values files. */}}
{{- define "ai-rm.controllerApply" -}}
{{- if or .Values.controller.apply (has "--apply" .Values.controller.extraArgs) -}}
{{- range .Values.controller.extraArgs -}}
{{- if hasPrefix "--namespace" . -}}
{{- fail "set placementNamespace instead of controller.extraArgs --namespace so apply RBAC matches the controller namespace" -}}
{{- end -}}
{{- end -}}
true
{{- end -}}
{{- end -}}

{{/* rm-controller spec (YAML): the pools, and the namespace of airm-placement. */}}
{{- define "ai-rm.controllerSpec" -}}
{{- if not .Values.controller.pools }}
{{- fail "controller.pools must list at least one pool" }}
{{- end }}
{{- toYaml (dict "namespace" (include "ai-rm.placementNamespace" .) "pools" .Values.controller.pools) }}
{{- end -}}
