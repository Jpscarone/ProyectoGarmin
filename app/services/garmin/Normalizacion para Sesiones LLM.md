Quiero que me generes un entrenamiento en dos formatos:

1) Primero en lenguaje natural (claro y breve).
2) Luego en formato estructurado EXACTO para importar.

Reglas del formato estructurado:

- Usar estas entidades en mayúscula:
  SESSION, SESSION_GROUP, BLOCK, REPEAT, END, END_REPEAT, END_GROUP

- Campos permitidos:
  DATE: formato YYYY-MM-DD
  SPORT: running | cycling | swimming | strength | walking | other
  NAME: nombre corto
  NOTES: texto corto

  STEP_TYPE: warmup | interval | recovery | steady | cooldown | rest | other

  VALUE: número
  UNIT: min | h | m | km

  INTENSITY: hr | pace | power | rpe | none
  ZONE: z1 | z2 | z3 | z4 | z5 | none

  COUNT: entero positivo

- Cada SESSION debe:
  - tener SPORT obligatorio
  - tener al menos un BLOCK
  - cerrar con END

- Cada BLOCK debe tener:
  - STEP_TYPE
  - VALUE
  - UNIT
  - INTENSITY
  - ZONE

- Repeticiones:
  - usar REPEAT
  - luego COUNT
  - luego BLOCKS
  - cerrar con END_REPEAT

- Multisport (triatlón o duatlón):
  - usar SESSION_GROUP
  - dentro varias SESSION en orden
  - cerrar con END_GROUP

- No inventar campos fuera de esta especificación.

- Mantener el formato limpio, consistente y sin texto extra.

Ejemplo válido:

SESSION
DATE: 2026-04-05
SPORT: running
NAME: Fondo progresivo

BLOCK
STEP_TYPE: warmup
VALUE: 15
UNIT: min
INTENSITY: hr
ZONE: z1

BLOCK
STEP_TYPE: steady
VALUE: 40
UNIT: min
INTENSITY: hr
ZONE: z2

END