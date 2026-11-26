# bedrock-agent-hierarchy

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/victorgalloo/bedrock-agent-hierarchy)
[![CI](https://github.com/victorgalloo/bedrock-agent-hierarchy/actions/workflows/ci.yml/badge.svg)](https://github.com/victorgalloo/bedrock-agent-hierarchy/actions/workflows/ci.yml)

[English](README.md) | Español

> **Estado: temprano.** Andamiaje v0. Las APIs van a cambiar.

Una plantilla pequeña y tipada en Python para **jerarquías gerente → subagente sobre Amazon Bedrock**.

## Qué es y por qué

Cuando las rutinas programadas de agentes pasan de cien, el problema deja de ser «¿funciona cada
una?» y pasa a ser **«¿quién se entera cuando una deja de funcionar?»**. Este proyecto extrae un
patrón que corre en producción (más de 100 rutinas programadas): un **orquestador** que decide solo,
**gerentes** de área que responden por un resultado, **agentes** que hacen el trabajo y
**subagentes** que hacen una sola cosa.

Los gerentes nunca le escriben a una persona. Le reportan al orquestador, y solo un conjunto fijo
de decisiones llega a un humano, como una pregunta de sí o no.

```mermaid
flowchart TD
    H([Humano]) ~~~ O
    O[Orquestador] -. "pregunta sí/no<br/>(solo temas fijos)" .-> H
    O --> M1[docs-manager]
    O --> M2[triage-manager]
    O --> M3[release-manager]
    M1 --> A1[docs-writer]
    M2 --> A2[issue-triager]
    M3 --> A3[release-notes]
    A1 --> S1[link-checker]
    A2 --> S2[duplicate-finder]
    A1 -. escala .-> M1
    M1 -. escala .-> O
```

## Inicio rápido

```bash
pip install -e ".[dev]"            # agrega ",bedrock" para boto3
python -m agent_hierarchy validate examples/org.yaml
pytest
```

```python
from agent_hierarchy import ChangeManager, HumanQuestion, Topic, escalate, escalate_to_human, load_org

org = load_org("examples/org.yaml")
escalate(org, "docs-writer", "dos corridas fallidas seguidas")   # -> docs-manager

escalate_to_human(org, "orchestrator", Topic.MONEY, HumanQuestion(
    question="¿Apruebo el plan anual de hosting de la documentación?",
    if_yes="La documentación pasa al plan de pago la próxima semana.",
    if_no="La documentación sigue en el plan gratuito con los límites actuales.",
))

cm = ChangeManager(org, root="examples", state_dir=".agent_hierarchy")
change = cm.request("docs-manager", "run-1", "docs-writer", "prompts/docs-writer.md",
                    why="Omitió los requisitos dos veces", measure="Páginas con requisitos, próximas 3 corridas")
# Change -> edita el archivo; Escalation -> el archivo estaba ocupado y se escaló al orquestador.
```

Los modelos corren con la API Converse de Bedrock (`BedrockModel("<id-de-modelo-claude-o-inference-profile>")`);
las pruebas usan `FakeModel` y nunca tocan la red.

## Enviar el resultado de una herramienta a Bedrock

Usa `BedrockModel.converse_with_tools(system, transcript, tool_config)` con un
modelo compatible con herramientas y un diccionario nativo `toolConfig` de Bedrock
(con `tools`). El adaptador hace una solicitud a Converse y devuelve el mensaje
completo del asistente y el motivo de parada. No ejecuta herramientas. La API
`converse` para solo texto no cambia.

Este ejemplo supone una sola solicitud para `lookup_docs`, una herramienta ficticia
de solo lectura. Valida el nombre y la entrada en tu aplicación antes de ejecutar
cualquier herramienta.

```python
turn = model.converse_with_tools(system, transcript, tool_config)
if turn.stop_reason == "tool_use":
    request = next(block["toolUse"] for block in turn.message["content"] if "toolUse" in block)
    if request["name"] == "lookup_docs" and request["input"] == {"page": "setup"}:
        reply = {
            "role": "user",
            "content": [{"toolResult": {
                "toolUseId": request["toolUseId"],
                "content": [{"json": {"found": True}}],
            }}],
        }
        turn = model.converse_with_tools(system, [*transcript, turn.message, reply], tool_config)
```

Conserva el mensaje completo del asistente en el historial, incluso si también incluye
texto. Si hay varias solicitudes de herramientas, envía un bloque de resultado por
cada identificador en un solo mensaje de usuario.

## Reintentos por límite de tasa y uso de tokens

`BedrockModel` reintenta los errores de límite de tasa (`ThrottlingException`,
`TooManyRequestsException`, `Throttling`, `RequestLimitExceeded` y respuestas HTTP 429) con espera
exponencial acotada (`max_retries=3`, `retry_base_delay=0.5`, `retry_max_delay=8.0`). Cualquier
otro error se propaga de inmediato. Usa `max_retries=0` para desactivar los reintentos del adaptador
si prefieres usar la configuración de reintentos de `boto3`.

Cada respuesta exitosa de Converse que incluye un bloque `usage` actualiza `model.last_usage` y se
acumula en `model.total_usage` (`TokenUsage`). `converse_with_tools` también expone el uso del turno
en `turn.usage`, y el callback opcional `on_usage` recibe cada `TokenUsage` al completarse la llamada:

```python
from agent_hierarchy.bedrock import BedrockModel, TokenUsage

def log_usage(usage: TokenUsage) -> None:
    print(f"tokens: in={usage.input_tokens} out={usage.output_tokens} total={usage.total_tokens}")

model = BedrockModel("us.example-profile-id", max_retries=3, on_usage=log_usage)
reply = model.converse("Revisa el área ficticia de documentación.", [{"role": "user", "text": "¿Estado?"}])
print(model.total_usage)
```

## Monitorear un área sin llamar al modelo

Ejecuta dos veces el ejemplo del área ficticia de documentación desde la raíz del repositorio:

```bash
python examples/monitor_area.py .agent_hierarchy/demo/docs.json
python examples/monitor_area.py .agent_hierarchy/demo/docs.json
```

Si el archivo aún no existe, la primera revisión muestra `wake: first run`; con los mismos datos,
la siguiente muestra `skip`. En una tarea programada, llama a `collect_snapshot` con la fecha de
revisión y el historial de corridas de un área (de la más antigua a la más reciente; incluye
corridas previas a la última revisión si hacen falta para detectar fallos consecutivos). Pasa los
identificadores de las rutinas bloqueadas, las caídas de KPI detectadas y los conflictos entre
agentes, además del número de encargos abiertos. Quien llama a la función lee sus propios registros
y decide qué se considera una caída de KPI o un conflicto.

Usa un archivo de estado distinto para cada área. En cada revisión, carga el estado anterior,
llama a `should_wake` y guarda el estado actual después de atender el resultado, incluso si no
despiertas al gerente. Esto permite detectar como nueva una excepción que se resolvió y volvió a
aparecer. Una nueva semana ISO o cualquier encargo abierto también despierta al gerente. No
ejecutes revisiones simultáneas de la misma área para que no se sobrescriba su estado.

## Reproducir una evaluación sin conexión

Ejecuta `python examples/eval_replay.py` para evaluar una revisión ficticia del área de
documentación con `FakeModel`. Muestra `docs-review: pass` y no hace llamadas de red.

Usa `agent_hierarchy.evals.replay_fixture(org, path, model)` con un archivo JSON que contenga
`name`, el prompt de sistema `system` y una lista no vacía `turns` con mensajes de usuario en
orden. La función agrega al prompt los nombres y las líneas de reporte del organigrama, y
pide que la respuesta sea solo JSON. Envía cada turno al modelo con todos los mensajes
anteriores. Cada respuesta debe ser un objeto JSON con una lista `events` (vacía si no pasó
nada) que incluya solo los eventos nuevos de ese turno:

| `type` del evento | Otros campos |
|---|---|
| `escalation` | `sender`, `recipient`, `topic` opcional (obligatorio si el destinatario es humano) |
| `change` | `reviewer`, `run_id`, `path` |
| `evaluation` | `change`, `verdict` (`keep` o `revert`), booleano opcional `restored` (por defecto, falso) |

La función también acepta un solo bloque de código JSON rodeado de texto. Si una respuesta no
es válida, se detiene y devuelve un puntaje fallido con el número de turno en `Score.error`.
Un archivo inválido sigue provocando un error de validación. El puntaje comprueba las rutas,
el número de cambios entre turnos y las restauraciones declaradas; la función no ejecuta ni
verifica los eventos. También puedes usar un `BedrockModel` configurado, que envía el prompt y
el contexto del organigrama al servicio en vivo. Aún no se pueden grabar corridas reales ni
generar informes de tendencias.

## Reglas de diseño

1. **El organigrama es un dato.** `org.yaml` es la única fuente de verdad y se valida al cargarse.
2. **Se escala un nivel a la vez.** Subagente → agente → gerente → orquestador. Solo el orquestador
   llega a un humano, y solo por: dinero, legal, compromisos externos, publicaciones a nombre de
   alguien, accesos y sesiones, hablar a nombre de alguien.
3. **Una pregunta por escalamiento a humano.** Sí o no, con qué pasa si sí y qué pasa si no; si pide
   una acción, la liga exacta a donde se hace.
4. **Cambios reversibles.** Un gerente cambia como máximo 2 archivos de prompt/skill de sus propios
   agentes por corrida. Cada cambio se respalda antes, se registra con *por qué* y *cómo se mide*,
   se evalúa después de N corridas (3 por defecto) y se restaura solo si el resultado es «revertir».
5. **Archivos ocupados.** Si otro revisor tocó un archivo hoy o ayer, se escala en lugar de editarlo.
6. **Despertar solo cuando algo cambió.** Un monitor barato decide si hace falta correr al gerente
   (excepción nueva, semana nueva, encargo abierto). Si no, no hay llamada al modelo.

## Estructura

| Módulo | Estado |
|---|---|
| `agent_hierarchy/org.py` | Carga y validación del organigrama |
| `agent_hierarchy/escalation.py` | Rutas de escalamiento y preguntas a humanos |
| `agent_hierarchy/changes.py` | Respaldo, límite de cambios, archivos ocupados, evaluación, restauración |
| `agent_hierarchy/monitor.py` | Recopila señales del área, guarda el estado y decide si despierta al gerente |
| `agent_hierarchy/bedrock.py` | Adaptador Converse con herramientas, reintentos por límite de tasa, uso de tokens + `FakeModel` |
| `agent_hierarchy/evals.py` | Puntúa eventos grabados y reproduce casos de prueba con un modelo |

## Ligas

- Open source de Omona: <https://omona.tech/open-source>
- [Cómo contribuir](CONTRIBUTING.md) · [Código de conducta](CODE_OF_CONDUCT.md) · [Seguridad](SECURITY.md)

Licencia [Apache-2.0](LICENSE).
