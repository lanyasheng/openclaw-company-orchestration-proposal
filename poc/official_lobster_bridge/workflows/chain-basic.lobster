name: chain-basic
args:
  topic:
    default: hello
  target:
    default: internal-demo
steps:
  - id: step_a
    command: |
      jq -n --arg topic '${topic}' '{status:"ok", topic:$topic}'

  - id: step_b
    stdin: $step_a.stdout
    command: |
      jq --arg target '${target}' '. + {target:$target, message:(.topic + " -> " + $target)}'
