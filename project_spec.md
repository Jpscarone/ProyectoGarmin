# Documento funcional base — App de planificación, sincronización Garmin y análisis de entrenamientos

## 1. Propósito del proyecto

Crear una aplicación web personal que permita:

1. Definir objetivos deportivos y planes de entrenamiento.
2. Guardar el entrenamiento planificado día por día.
3. Conectarse automáticamente a Garmin Connect mediante una integración no oficial.
4. Sincronizar actividades realizadas, métricas de salud y datos de contexto.
5. Comparar el entrenamiento planificado con el entrenamiento real.
6. Analizar el cumplimiento global y por bloques, especialmente en sesiones estructuradas con laps.
7. Generar un resumen claro y útil para revisión técnica y ajuste del plan.

La aplicación no estará pensada como visor de archivos `.FIT` o `.GPX`, sino como sistema de análisis sobre datos normalizados y estructurados.

---

## 2. Problema que resuelve

Actualmente el flujo manual presenta varios problemas:

* Los archivos exportados desde Garmin Connect no siempre se pueden analizar de forma confiable.
* Los resúmenes básicos de la actividad no alcanzan para validar entrenamientos por intervalos.
* La comparación entre lo planificado y lo realizado es inconsistente.
* El análisis pierde contexto importante como sueño, estrés, HRV, Body Battery y condiciones externas.

La app debe resolver eso centralizando el plan, la sincronización y el análisis en un solo sistema.

---

## 3. Usuarios y alcance

### Consideración clave de uso real

La persona usuaria no realiza únicamente sesiones aisladas de una sola disciplina. También puede entrenar y competir en formatos multideporte.

Por lo tanto, el sistema debe soportar desde el inicio:

* días con más de una sesión planificada
* días con más de una actividad real
* sesiones compuestas o encadenadas
* entrenamientos tipo brick
* carreras de duatlón
* carreras de triatlón

Esto implica que la arquitectura no debe asumir una única sesión ni una única actividad por día.

### Usuario principal

Una sola persona usuaria, dueña de la cuenta Garmin, que practica varios deportes y sigue planes de entrenamiento estructurados.

### Deportes soportados en la primera versión

* Ciclismo de ruta
* Ciclismo MTB
* Running de calle
* Trail running
* Natación

### Alcance inicial

La app será de uso personal, instalada localmente o en un entorno privado, sin necesidad de multiusuario en la primera etapa.

---

## 4. Objetivos funcionales principales

La aplicación debe permitir:

### 4.1. Gestión del perfil del atleta

Guardar y editar:

* nombre
* peso
* altura
* edad
* sexo
* frecuencia cardíaca máxima
* frecuencia cardíaca en reposo
* zonas de frecuencia cardíaca
* FTP y zonas de potencia si corresponde
* cadencia objetivo para running y ciclismo
* otros parámetros fisiológicos relevantes

### 4.2. Gestión de objetivos deportivos

Crear y editar objetivos como:

* carrera o evento
* fecha
* deporte
* distancia
* desnivel esperado
* prioridad
* notas

### 4.3. Gestión del plan de entrenamiento

Permitir cargar un plan de entrenamiento día por día con sesiones detalladas.

Cada día puede contener:

* una sesión única
* dos o más sesiones separadas
* una sesión compuesta formada por varias disciplinas consecutivas

Ejemplos:

* natación por la mañana y running por la tarde
* ciclismo seguido de running como brick
* competencia multideporte con varias etapas

Cada sesión debe poder guardarse en dos formas:

#### a) Texto original legible

Ejemplo:

* “4 × 6 min en Z3 (145–160 ppm) con 3 min Z1-Z2 entre cada uno”

#### b) Estructura interna normalizada

Ejemplo:

* warmup
* bloques de trabajo
* bloques de recuperación
* cooldown
* objetivos fisiológicos o técnicos

Además, el sistema debe permitir agrupar varias sesiones relacionadas dentro de una misma unidad lógica de entrenamiento o competencia.

### 4.4. Sincronización con Garmin Connect

La app debe conectarse automáticamente a Garmin Connect usando integración no oficial y debe poder obtener:

* actividades realizadas
* laps de cada actividad
* métricas de salud del día
* métricas de carga o recuperación si están disponibles

### 4.5. Importación y normalización de actividades

Cada actividad sincronizada debe guardarse en formato entendible por el sistema, evitando depender del archivo bruto como fuente de análisis.

### 4.6. Obtención automática de condiciones externas

La app debe consultar una fuente meteorológica externa para recuperar condiciones históricas del momento en que se realizó la actividad.

### 4.7. Comparación entre plan y ejecución

La app debe comparar:

* lo planificado
* lo realizado
* el estado fisiológico del día
* el clima/contexto

### 4.8. Análisis del cumplimiento

Debe generar:

* score de cumplimiento general
* evaluación por bloque o por lap
* observaciones automáticas
* alertas o sugerencias básicas

---

## 5. Tipos de sesiones que debe soportar

### 5.1. Sesiones simples

Ejemplos:

* 50 min en Z2
* trote suave
* salida larga continua
* natación continua

Estas pueden evaluarse con métricas globales.

### 5.2. Sesiones estructuradas

Ejemplos:

* 4 × 6 min en Z3 con 3 min suaves
* 6 × 2 min fuertes + 1 min suave
* 8 strides de 20 s
* bloques de cadencia
* repeticiones en natación
* series en subida

Estas deben evaluarse por bloques y, preferentemente, usando laps marcados en Garmin.

### 5.3. Doble turno o sesiones múltiples en un mismo día

Ejemplos:

* natación por la mañana + running por la tarde
* ciclismo por la mañana + gimnasio o running más tarde

Estas deben poder guardarse como varias sesiones independientes dentro del mismo día, con orden, disciplina y análisis propio.

### 5.4. Sesiones compuestas o encadenadas

Ejemplos:

* brick: bici + running
* natación + running
* ciclismo + transición breve + running

Estas deben poder modelarse como una unidad compuesta por varias partes relacionadas.

### 5.5. Eventos multideporte

Ejemplos:

* duatlón
* triatlón

Estos deben poder analizarse como una estructura formada por múltiples segmentos y, cuando corresponda, transiciones.

## 6. Rol de los laps

Los laps serán una pieza central del sistema.

### Regla de diseño

Cuando el usuario marque laps en el reloj o dispositivo Garmin durante una sesión estructurada, la aplicación debe usar esos laps como unidad principal de análisis.

### Beneficio

Esto evita tener que adivinar automáticamente dónde empieza y termina cada intervalo, y mejora mucho la precisión del análisis.

### Fallback

Si una actividad no tiene laps útiles, el sistema podrá hacer análisis global o aproximado, pero con menor precisión.

---

## 7. Datos que debe guardar la aplicación

## 7.1. Datos del atleta

* id
* nombre
* peso
* altura
* edad
* sexo
* FC máxima
* FC reposo
* zonas de FC
* FTP
* zonas de potencia
* cadencias objetivo
* fecha de última actualización

## 7.2. Datos del objetivo deportivo

* id
* nombre del objetivo
* deporte
* fecha
* distancia
* desnivel
* prioridad
* notas
* estado

## 7.3. Datos del plan

* id del plan
* objetivo asociado
* fecha
* referencia al día de entrenamiento
* deporte
* nombre de la sesión
* descripción en texto
* estructura normalizada de pasos
* duración esperada
* distancia esperada si aplica
* zonas objetivo
* comentarios
* orden dentro del día
* indicador de si la sesión forma parte de una sesión compuesta o grupo
* identificador de grupo si corresponde
* tipo de grupo si corresponde (doble turno, brick, duatlón, triatlón, otro)

## 7.4. Datos globales de actividad

* activity_id de Garmin
* fecha
* hora de inicio
* deporte
* duración
* distancia
* desnivel positivo
* desnivel negativo
* FC promedio
* FC máxima
* ritmo promedio o velocidad promedio
* potencia promedio y máxima si existe
* cadencia promedio y máxima si existe
* tiempo en zonas de FC
* tiempo en zonas de potencia si existe
* training effect aeróbico
* training effect anaeróbico
* training load
* calorías
* ubicación inicial si está disponible

## 7.5. Datos por lap

Para cada lap:

* lap_number
* lap_start_time
* lap_duration
* lap_distance
* lap_avg_hr
* lap_max_hr
* lap_avg_power si existe
* lap_max_power si existe
* lap_avg_speed o lap_avg_pace
* lap_avg_cadence
* lap_max_cadence
* lap_elevation_gain
* lap_elevation_loss
* tiempo en zonas de FC por lap
* tiempo en zonas de potencia por lap si existe

## 7.6. Datos fisiológicos diarios

* fecha
* horas de sueño
* sleep score
* deep sleep
* REM
* despertares
* estrés promedio
* estrés máximo
* tiempo en estrés alto
* Body Battery inicio
* Body Battery mínimo
* Body Battery fin
* HRV status
* HRV promedio si existe
* resting heart rate
* avg daily heart rate
* recovery time si existe
* VO2max si existe

## 7.7. Datos meteorológicos

### Datos de inicio

* temperatura
* humedad
* viento velocidad
* viento dirección
* presión
* precipitación
* sensación térmica o variable equivalente

### Resumen durante actividad

* temp_min
* temp_max
* viento_promedio
* precipitación_total

---

## 8. Datos relevantes por deporte

### 8.1. Ciclismo ruta y MTB

Guardar especialmente:

* velocidad
* cadencia
* potencia si existe
* desnivel
* tiempo detenido si es posible
* laps con FC, potencia, cadencia y velocidad

### 8.2. Running de calle

Guardar especialmente:

* ritmo
* FC
* cadencia
* longitud de zancada si existe
* tiempo de contacto con el suelo si existe
* oscilación vertical o ratio vertical si existe

### 8.3. Trail running

Guardar todo lo del running más:

* desnivel positivo y negativo
* elevación por lap
* análisis conjunto de ritmo + FC + desnivel

### 8.4. Natación

Guardar especialmente:

* distancia
* duración
* ritmo por 100 m
* SWOLF si existe
* cantidad de brazadas si existe
* ritmo por lap
* distancia por lap

---

## 9. Lógica de comparación y análisis

## 9.1. Comparación básica

El sistema debe poder comparar para cualquier sesión:

* duración esperada vs real
* distancia esperada vs real si aplica
* zona esperada vs zona real
* intensidad global esperada vs real

## 9.2. Comparación avanzada por bloques

En sesiones estructuradas debe poder comparar:

* duración de cada bloque
* intensidad de cada bloque
* tiempo efectivo dentro de la zona objetivo
* recuperación entre bloques
* consistencia entre repeticiones
* fatiga progresiva
* enfriamiento

## 9.3. Evaluación contextual

La interpretación del entrenamiento debe considerar también:

* sueño
* estrés
* Body Battery
* HRV
* temperatura y viento
* desnivel real

## 9.4. Comparación de múltiples sesiones en el mismo día

Cuando existan dos o más sesiones en una fecha, el sistema debe poder:

* vincular cada actividad real con su sesión planificada correcta
* analizar cada sesión por separado
* ofrecer una visión resumida del día completo

## 9.5. Comparación de sesiones compuestas

Cuando varias disciplinas formen parte de una misma unidad de entrenamiento, el sistema debe poder:

* analizar cada parte por separado
* generar una evaluación combinada de la sesión compuesta
* reflejar relación entre segmentos consecutivos

Ejemplos:

* cómo llega el running después del ciclismo en un brick
* cómo cambia el pulso o el ritmo al pasar de una disciplina a otra

## 9.6. Comparación de eventos multideporte

Para duatlón y triatlón, el sistema debe poder analizar:

* cada segmento individual
* transiciones si están disponibles
* tiempo total
* pacing general
* deterioro o variación del rendimiento entre segmentos

## 10. Resultado esperado del análisis

La aplicación debe generar un informe entendible y útil.

### 10.1. Resultado general

* porcentaje de cumplimiento
* estado general: correcto / parcial / no cumplido

### 10.2. Resultado por bloques o laps

Ejemplo:

* calentamiento: correcto
* intervalo 1: correcto
* recuperación 1: correcta
* intervalo 2: algo alto de pulso
* intervalo 3: correcto
* intervalo 4: incompleto
* cooldown: corto

### 10.3. Observaciones automáticas

Ejemplos:

* buen control en los primeros bloques
* deriva cardíaca en la segunda mitad
* recuperación insuficiente entre esfuerzos
* intensidad adecuada, pero con sueño pobre previo
* FC elevada explicable por calor

### 10.4. Recomendación simple

Ejemplos:

* mantener planificación
* repetir un trabajo similar
* bajar carga del día siguiente
* revisar pacing de salida

### 10.5. Resultado combinado para doble turno o sesión compuesta

Cuando corresponda, además del análisis individual, la aplicación debe generar:

* resumen del día completo
* resumen del bloque compuesto
* conclusión general del conjunto

Ejemplos:

* natación correcta y running correcto, pero con fatiga acumulada al final del día
* brick bien ejecutado, aunque el running salió demasiado alto de pulso al inicio
* ciclismo correcto, transición larga, running por debajo de lo esperado

### 10.6. Resultado multideporte

En duatlón o triatlón, el informe debe poder mostrar:

* resultado por segmento
* resultado global del evento
* observaciones de transición o deterioro entre etapas

## 11. Requisitos no funcionales

La aplicación debe ser:

* clara de usar
* modular
* mantenible
* extensible a más deportes o métricas
* usable en entorno local
* tolerante a errores de sincronización

### Requisitos técnicos iniciales sugeridos

* backend en Python
* framework FastAPI
* base de datos SQLite en primera etapa
* ORM SQLAlchemy
* migraciones con Alembic
* validaciones con Pydantic
* frontend simple con Jinja2 + HTMX
* integración Garmin separada como módulo independiente
* integración clima separada como módulo independiente
* lógica de análisis separada del acceso a datos

---

## 12. Decisiones técnicas de producto

### 12.1. Fuente principal de análisis

La fuente principal no será el archivo `.FIT` o `.GPX`, sino los datos normalizados que la app extraiga y guarde.

### 12.2. Prioridad de análisis

Para sesiones estructuradas, la unidad principal será el lap.

Cuando existan varias actividades relacionadas en el mismo día, el sistema deberá soportar dos niveles de análisis:

* análisis individual por actividad o sesión
* análisis combinado por día o por grupo multideporte

### 12.3. Interfaz de usuario inicial

Se priorizará una interfaz web funcional, moderna y simple antes que una interfaz compleja tipo dashboard pesado.

### 12.4. Alcance inicial del análisis

La primera versión debe centrarse en:

* comparación plan vs actividad
* análisis por laps
* contexto fisiológico
* contexto climático

No es prioridad inicial:

* predicción avanzada
* machine learning
* sugerencias automáticas complejas
* sincronización multiusuario

---

## 13. Fases del desarrollo

## Fase 1 — Núcleo del sistema

* estructura del proyecto
* base de datos
* perfil del atleta
* objetivos
* día de entrenamiento
* plan diario
* sesiones estructuradas
* soporte para múltiples sesiones por día
* soporte para grupos de sesiones

## Fase 2 — Integración Garmin

* autenticación
* sincronización de actividades
* sincronización de laps
* sincronización de salud diaria

## Fase 3 — Clima histórico

* integración con proveedor meteorológico
* guardado de clima al inicio y resumen durante actividad

## Fase 4 — Motor de análisis

* comparación global
* comparación por laps
* score de cumplimiento
* observaciones automáticas

## Fase 5 — Interfaz de revisión

* agenda de entrenamientos
* detalle de sesión
* detalle de actividad sincronizada
* informe comparativo

---

## 14. Criterios de éxito del MVP

El MVP será considerado exitoso si permite:

1. Cargar planes de entrenamiento estructurados.
2. Cargar más de una sesión en un mismo día.
3. Definir sesiones compuestas o agrupadas.
4. Sincronizar actividades reales desde Garmin.
5. Recuperar laps útiles de las sesiones.
6. Traer métricas básicas de salud diaria.
7. Traer clima histórico automático.
8. Comparar una sesión planificada contra una actividad real.
9. Comparar un día con múltiples actividades.
10. Mostrar un informe por bloques entendible y técnicamente útil.

## 15. Visión a futuro

A futuro, la app podrá extenderse para:

* ajustar automáticamente microciclos
* detectar fatiga acumulada
* comparar semanas o bloques
* generar reportes PDF
* exportar paquetes listos para análisis externo
* incorporar gráficos avanzados
* sumar más deportes o sensores

---

## 16. Resumen ejecutivo

La aplicación será un sistema web personal para planificación, sincronización y análisis de entrenamientos, con foco en validar si el usuario cumplió una sesión según lo planificado.

Su fortaleza principal será:

* usar laps como base de análisis en sesiones estructuradas
* incorporar contexto fisiológico diario
* incorporar condiciones climáticas automáticas
* normalizar toda la información para hacer comparaciones consistentes y útiles

El objetivo no es solamente almacenar datos, sino transformar entrenamientos planificados y actividades reales en una evaluación técnica clara, práctica y accionable.

---

# Arquitectura inicial del proyecto

## 17. Decisión de arquitectura general

La aplicación se construirá como una web app monolítica modular.

Esto significa:

* un solo proyecto principal
* backend y frontend servidos desde la misma aplicación en la primera etapa
* módulos internos bien separados por responsabilidad

### Motivo de esta decisión

Para un MVP personal, esta arquitectura ofrece ventajas claras:

* menor complejidad de despliegue
* menos puntos de falla
* desarrollo más rápido
* mantenimiento más simple
* posibilidad de separar servicios más adelante si el proyecto crece

En la primera versión no conviene dividir en microservicios.

---

## 18. Stack técnico recomendado

### Backend

* Python 3.12
* FastAPI
* SQLAlchemy 2.x
* Alembic
* Pydantic v2

### Frontend

* Jinja2
* HTMX
* CSS moderno propio o utilitario liviano

### Base de datos

* SQLite para la primera versión

### Integraciones externas

* Garmin Connect vía librería no oficial
* Open-Meteo para clima histórico

### Tareas programadas

* APScheduler o tareas manuales disparadas por botón en la primera etapa

### Utilidades

* httpx para llamadas HTTP
* pandas solo cuando realmente aporte valor
* loguru o logging estándar para trazabilidad

---

## 19. Principios de diseño del código

El código debe respetar estas reglas:

### 19.1. Separación clara de responsabilidades

No mezclar en un mismo archivo:

* acceso a base de datos
* lógica de negocio
* integración con APIs externas
* renderizado de vistas

### 19.2. Los módulos externos deben estar encapsulados

Garmin y clima deben vivir en módulos propios para que, si mañana cambia la librería o el proveedor, el resto del sistema no se rompa.

### 19.3. El análisis debe ser independiente del origen del dato

La lógica que compara plan vs ejecución no debe depender directamente de Garmin. Debe trabajar sobre datos ya normalizados y guardados.

### 19.4. La interfaz no debe contener lógica crítica

Las reglas de comparación, validación y análisis deben estar en servicios de backend, no en JavaScript ni en plantillas HTML.

---

## 20. Estructura sugerida del proyecto

```text
training_app/
├─ app/
│  ├─ main.py
│  ├─ config.py
│  ├─ db/
│  │  ├─ base.py
│  │  ├─ session.py
│  │  └─ models/
│  │     ├─ athlete.py
│  │     ├─ goal.py
│  │     ├─ training_plan.py
│  │     ├─ planned_session.py
│  │     ├─ activity.py
│  │     ├─ activity_lap.py
│  │     ├─ daily_health.py
│  │     ├─ weather.py
│  │     └─ analysis_report.py
│  ├─ schemas/
│  │  ├─ athlete.py
│  │  ├─ goal.py
│  │  ├─ training_plan.py
│  │  ├─ activity.py
│  │  ├─ health.py
│  │  └─ analysis.py
│  ├─ routers/
│  │  ├─ web.py
│  │  ├─ athletes.py
│  │  ├─ goals.py
│  │  ├─ plans.py
│  │  ├─ activities.py
│  │  ├─ analysis.py
│  │  └─ sync.py
│  ├─ services/
│  │  ├─ garmin/
│  │  │  ├─ client.py
│  │  │  ├─ auth.py
│  │  │  ├─ activity_sync.py
│  │  │  └─ health_sync.py
│  │  ├─ weather/
│  │  │  ├─ client.py
│  │  │  └─ weather_service.py
│  │  ├─ planning/
│  │  │  ├─ parser.py
│  │  │  └─ session_builder.py
│  │  ├─ analysis/
│  │  │  ├─ comparator.py
│  │  │  ├─ lap_analyzer.py
│  │  │  ├─ scoring.py
│  │  │  └─ recommendations.py
│  │  └─ sync_orchestrator.py
│  ├─ templates/
│  │  ├─ base.html
│  │  ├─ dashboard.html
│  │  ├─ athletes/
│  │  ├─ goals/
│  │  ├─ plans/
│  │  ├─ activities/
│  │  └─ analysis/
│  ├─ static/
│  │  ├─ css/
│  │  └─ js/
│  └─ utils/
│     ├─ dates.py
│     ├─ zones.py
│     └─ formatters.py
├─ migrations/
├─ tests/
│  ├─ unit/
│  ├─ integration/
│  └─ fixtures/
├─ requirements.txt
├─ .env.example
└─ README.md
```

---

## 21. Módulos principales

## 21.1. Módulo atleta

Responsabilidad:

* guardar perfil fisiológico
* almacenar zonas de FC y potencia
* servir de base para el análisis

## 21.2. Módulo objetivos

Responsabilidad:

* crear eventos objetivo
* asociar planes a cada objetivo

## 21.3. Módulo planes y sesiones

Responsabilidad:

* guardar entrenamiento diario
* soportar texto libre y estructura normalizada
* diferenciar sesiones simples y estructuradas
* permitir múltiples sesiones en una misma fecha
* permitir agrupar sesiones relacionadas en un mismo bloque o evento

## 21.4. Módulo Garmin

Responsabilidad:

* autenticación
* sincronización de actividades
* sincronización de laps
* sincronización de métricas diarias
* normalización de datos hacia el modelo interno

## 21.5. Módulo clima

Responsabilidad:

* consultar clima histórico por latitud, longitud, fecha y rango horario
* guardar snapshot al inicio y resumen durante la actividad

## 21.6. Módulo análisis

Responsabilidad:

* comparar plan vs ejecución
* analizar laps
* calcular score de cumplimiento
* generar observaciones
* producir un informe persistible

## 21.7. Módulo web

Responsabilidad:

* mostrar dashboard
* mostrar calendario o agenda
* mostrar detalle de plan
* mostrar actividad sincronizada
* mostrar informe de análisis

---

## 22. Flujo funcional principal

### Flujo 1 — Crear objetivo y plan

1. El usuario crea un objetivo deportivo.
2. Carga sesiones por día.
3. Cada sesión se guarda en texto y en estructura interna.
4. Un día puede contener una o varias sesiones.
5. Varias sesiones pueden agruparse dentro de una misma unidad compuesta.

### Flujo 2 — Sincronizar actividad real

1. El usuario dispara una sincronización manual o programada.
2. El módulo Garmin busca actividades nuevas.
3. Guarda actividad global, laps y métricas diarias de salud.
4. El módulo clima consulta condiciones externas para esa actividad.
5. Toda la información queda persistida en la base local.

### Flujo 3 — Comparar plan y ejecución

1. El sistema identifica la o las sesiones planificadas correspondientes a esa fecha.
2. Vincula cada actividad real con su sesión esperada.
3. Si hay un grupo compuesto, también identifica la relación entre actividades del mismo bloque.
4. El motor de análisis compara datos globales y por lap.
5. Genera score, observaciones y conclusión.
6. El informe queda disponible en la interfaz.

## 23. Modelo lógico de base de datos

## 23.1. Entidades principales

Las entidades mínimas del sistema serán:

* athlete
* athlete_hr_zone
* athlete_power_zone
* goal
* training_plan
* training_day
* session_group
* planned_session
* planned_session_step
* garmin_activity
* garmin_activity_lap
* daily_health_metric
* activity_weather
* analysis_report
* analysis_report_item

## 24. Relaciones principales

### athlete

Se relaciona con:

* goals
* training_plans
* training_days
* garmin_activities
* daily_health_metrics

### goal

Se relaciona con:

* training_plans

### training_plan

Se relaciona con:

* training_days
* athlete
* goal

### training_day

Se relaciona con:

* planned_sessions
* analysis_reports de resumen diario si se implementan

### session_group

Se relaciona con:

* planned_sessions
* potencialmente múltiples garmin_activities
* analysis_reports de grupo

### planned_session

Se relaciona con:

* planned_session_steps
* training_day
* session_group opcional
* analysis_reports
* potencialmente una garmin_activity vinculada

### garmin_activity

Se relaciona con:

* garmin_activity_laps
* activity_weather
* analysis_reports
* planned_session opcional
* session_group opcional

### analysis_report

Se relaciona con:

* planned_session opcional
* garmin_activity opcional
* training_day opcional
* session_group opcional
* analysis_report_items

## 25. Decisión sobre el parser del entrenamiento

El sistema debe aceptar que muchas sesiones se carguen inicialmente en lenguaje natural.

Ejemplo:

* “4 × 6 min en Z3 (145–160 ppm) con 3 min Z1-Z2 entre cada uno”

Pero internamente la app debe convertir eso a pasos estructurados.

### Regla importante

La app no debe depender para siempre del texto libre.

Debe existir un modelo estructurado con tipos de paso como:

* warmup
* work
* recovery
* cooldown
* drills
* strides
* steady
* long_run
* swim_repeat

Esto será clave para que el análisis después sea confiable.

---

## 26. Estrategia de sincronización inicial

Para el MVP conviene empezar con sincronización manual, no automática.

### Botones iniciales sugeridos

* Sincronizar actividades nuevas
* Sincronizar salud de hoy
* Analizar sesión del día

### Motivo

La automatización completa se puede agregar después. Primero conviene que el flujo funcione bien bajo control manual.

---

## 27. Estrategia de matching entre plan y actividad

El sistema debe vincular una actividad real con una sesión planificada usando estas reglas, en este orden:

1. misma fecha
2. mismo deporte o deporte compatible
3. proximidad horaria si hay más de una actividad
4. coincidencia aproximada de duración o distancia
5. pertenencia a un grupo compuesto si corresponde
6. confirmación manual del usuario si hay ambigüedad

Esto evita vincular mal dos actividades del mismo día.

Cuando haya varias actividades en una fecha, el sistema no debe asumir automáticamente que la primera coincide con la primera sesión si no hay evidencia suficiente.

## 28. Estrategia de análisis del MVP

En la primera versión, el motor de análisis debe cubrir bien estos casos:

### Sesiones simples

* duración
* zona cardíaca predominante
* distancia o desnivel si aplica

### Sesiones con intervalos y laps

* duración por lap
* intensidad por lap
* recuperación por lap
* cumplimiento de bloques

### Sesiones con contexto fisiológico relevante

* sueño insuficiente
* estrés alto
* Body Battery bajo
* calor o viento marcados

### Días con múltiples sesiones

* análisis por sesión individual
* resumen básico del conjunto del día

### Sesiones compuestas tipo brick

* análisis por segmento
* análisis combinado del bloque

No hace falta en el MVP:

* detección automática avanzada de fatiga crónica
* predicción de rendimiento
* análisis biomecánico complejo
* modelado avanzado de transiciones si Garmin no las expone bien

## 29. Pantallas mínimas del MVP

### Dashboard

Debe mostrar:

* objetivo actual
* próximas sesiones
* últimas actividades sincronizadas
* accesos rápidos a sincronización y análisis
* si el día tiene doble turno o sesión compuesta, indicarlo claramente

### Perfil del atleta

* datos personales
* zonas de FC
* zonas de potencia

### Objetivos

* lista de objetivos
* formulario de alta/edición

### Plan

* vista por calendario o lista
* detalle de cada sesión
* soporte para varias sesiones en un mismo día
* visualización de grupos o bloques compuestos

### Actividades

* lista de actividades sincronizadas
* detalle global + laps

### Análisis

* comparación sesión planificada vs actividad real
* resultado general
* detalle por bloques/laps
* observaciones
* soporte para análisis combinado por día o por grupo cuando corresponda

## 30. Orden recomendado de implementación

### Etapa 1

* estructura del proyecto
* configuración
* conexión a base de datos
* modelos principales
* migraciones
* página inicial funcionando

### Etapa 2

* CRUD de atleta
* CRUD de objetivos
* CRUD de planes, días y sesiones
* soporte para múltiples sesiones por día
* soporte para grupos de sesiones

### Etapa 3

* parser básico de sesiones estructuradas
* almacenamiento de pasos

### Etapa 4

* integración Garmin mínima
* traer actividad global
* traer laps
* guardar salud diaria

### Etapa 5

* integración clima histórico

### Etapa 6

* comparador plan vs actividad
* scoring de cumplimiento
* observaciones

### Etapa 7

* refinamiento visual
* validaciones mejores
* testing

---

## 31. Criterio de trabajo con Codex

El proyecto no debe pedirse a Codex en un solo bloque gigantesco.

La estrategia correcta será:

* usar este documento como contexto rector
* pedir tareas pequeñas y concretas
* revisar cada entrega antes de seguir

### Tipo de tareas a pedir

* crear la estructura inicial del repo
* implementar los modelos SQLAlchemy
* crear migraciones iniciales
* construir CRUD de planes
* integrar Garmin en un servicio aislado
* construir el comparador por laps

---

## 32. Resumen técnico de la arquitectura

La app será un monolito modular en Python con FastAPI, SQLite y frontend server-rendered.

Su núcleo funcional estará basado en:

* sesiones planificadas estructuradas
* actividades Garmin normalizadas
* laps como unidad central de análisis
* salud diaria como contexto fisiológico
* clima histórico como contexto externo
* motor de comparación desacoplado del origen de datos
* soporte para múltiples sesiones por día
* soporte para sesiones compuestas y multideporte

Esta arquitectura es suficiente para construir un MVP robusto, entendible y extensible sin meter complejidad innecesaria al principio.

---

# Esquema inicial de base de datos

## 33. Objetivo del esquema inicial

El esquema de base de datos debe permitir construir un MVP sólido sin sobrediseñar el sistema.

Debe ser capaz de soportar:

* perfil del atleta
* zonas fisiológicas
* objetivos deportivos
* planes de entrenamiento
* días con una o varias sesiones
* grupos de sesiones compuestas o multideporte
* actividades Garmin
* laps por actividad
* métricas diarias de salud
* clima histórico asociado a cada actividad
* reportes de análisis individuales y combinados

La prioridad es que el modelo sea claro y extensible.

---

## 34. Convenciones generales de modelado

### 34.1. Claves primarias

Todas las tablas tendrán una clave primaria interna tipo entero autoincremental llamada `id`, salvo casos puntuales donde convenga además guardar un identificador externo.

### 34.2. Timestamps comunes

Siempre que tenga sentido, las tablas deben incluir:

* `created_at`
* `updated_at`

### 34.3. Identificadores externos

Cuando un registro venga de Garmin u otro sistema, se debe guardar además el identificador externo original.

### 34.4. JSON controlado

Se podrá usar JSON solo en campos donde aporte flexibilidad real, por ejemplo:

* estructura normalizada de una sesión
* métricas adicionales poco estables
* payload crudo opcional para depuración

Pero la información central de análisis debe vivir en columnas normales siempre que sea posible.

---

## 35. Tablas principales

## 35.1. athlete

Representa el perfil del atleta.

### Campos sugeridos

* `id`
* `name`
* `birth_date` opcional
* `sex` opcional
* `height_cm`
* `weight_kg`
* `max_hr`
* `resting_hr`
* `lactate_threshold_hr` opcional
* `running_threshold_pace_sec_km` opcional
* `cycling_ftp` opcional
* `running_target_cadence_min` opcional
* `running_target_cadence_max` opcional
* `cycling_target_cadence_min` opcional
* `cycling_target_cadence_max` opcional
* `vo2max` opcional
* `notes` opcional
* `created_at`
* `updated_at`

---

## 35.2. athlete_hr_zone

Zonas de frecuencia cardíaca del atleta.

### Campos sugeridos

* `id`
* `athlete_id`
* `zone_name`
  Ejemplo: Z1, Z2, Z3, Z4, Z5
* `zone_order`
* `min_hr`
* `max_hr`
* `created_at`
* `updated_at`

---

## 35.3. athlete_power_zone

Zonas de potencia del atleta.

### Campos sugeridos

* `id`
* `athlete_id`
* `sport_type`
  Ejemplo: cycling
* `zone_name`
* `zone_order`
* `min_power`
* `max_power`
* `created_at`
* `updated_at`

---

## 35.4. goal

Objetivos o eventos deportivos.

### Campos sugeridos

* `id`
* `athlete_id`
* `name`
* `sport_type`
* `event_type`
  Ejemplo: race, triathlon, duathlon, test, personal_goal
* `event_date`
* `distance_km` opcional
* `elevation_gain_m` opcional
* `priority` opcional
* `location_name` opcional
* `notes` opcional
* `status`
  Ejemplo: planned, completed, cancelled
* `created_at`
* `updated_at`

---

## 35.5. training_plan

Representa un plan asociado a un objetivo o período.

### Campos sugeridos

* `id`
* `athlete_id`
* `goal_id` opcional
* `name`
* `start_date`
* `end_date`
* `description` opcional
* `status`
  Ejemplo: draft, active, archived
* `created_at`
* `updated_at`

---

## 35.6. training_day

Representa un día dentro de un plan.

### Campos sugeridos

* `id`
* `training_plan_id`
* `athlete_id`
* `day_date`
* `day_notes` opcional
* `day_type` opcional
  Ejemplo: single_session, double_session, multisport, rest_day
* `created_at`
* `updated_at`

### Restricción recomendada

* índice único por `training_plan_id + day_date`

---

## 35.7. session_group

Agrupa sesiones relacionadas dentro de un mismo día o evento.

### Uso

Sirve para:

* doble turno relacionado
* brick
* duatlón
* triatlón
* cualquier conjunto compuesto

### Campos sugeridos

* `id`
* `training_day_id`
* `name`
* `group_type`
  Ejemplo: double_session, brick, duathlon, triathlon, multisport, custom
* `group_order` opcional
* `notes` opcional
* `created_at`
* `updated_at`

---

## 35.8. planned_session

Representa una sesión planificada concreta.

### Campos sugeridos

* `id`
* `training_day_id`
* `session_group_id` opcional
* `athlete_id`
* `sport_type`
* `discipline_variant` opcional
  Ejemplo: road_cycling, mtb, road_running, trail_running, pool_swim, open_water_swim
* `name`
* `description_text`
* `structured_data_json` opcional
* `session_type`
  Ejemplo: easy, intervals, long, tempo, technique, race, brick_part, multisport_part
* `session_order`
* `planned_start_time` opcional
* `expected_duration_min` opcional
* `expected_distance_km` opcional
* `expected_elevation_gain_m` opcional
* `target_hr_zone` opcional
* `target_power_zone` opcional
* `target_notes` opcional
* `is_key_session`
* `created_at`
* `updated_at`

### Restricción recomendada

* índice por `training_day_id + session_order`

---

## 35.9. planned_session_step

Guarda los pasos estructurados de una sesión.

### Campos sugeridos

* `id`
* `planned_session_id`
* `step_order`
* `step_type`
  Ejemplo: warmup, work, recovery, cooldown, drills, strides, steady, transition, swim_repeat
* `repeat_count` opcional
* `duration_sec` opcional
* `distance_m` opcional
* `target_hr_min` opcional
* `target_hr_max` opcional
* `target_power_min` opcional
* `target_power_max` opcional
* `target_pace_min_sec_km` opcional
* `target_pace_max_sec_km` opcional
* `target_cadence_min` opcional
* `target_cadence_max` opcional
* `target_notes` opcional
* `created_at`
* `updated_at`

---

## 35.10. garmin_activity

Representa una actividad real sincronizada desde Garmin.

### Campos sugeridos

* `id`
* `athlete_id`
* `garmin_activity_id`
* `training_day_id` opcional
* `planned_session_id` opcional
* `session_group_id` opcional
* `activity_name` opcional
* `sport_type`
* `discipline_variant` opcional
* `is_multisport`
* `start_time`
* `end_time` opcional
* `timezone_name` opcional
* `duration_sec`
* `moving_duration_sec` opcional
* `distance_m` opcional
* `elevation_gain_m` opcional
* `elevation_loss_m` opcional
* `avg_hr` opcional
* `max_hr` opcional
* `avg_power` opcional
* `max_power` opcional
* `normalized_power` opcional
* `avg_speed_mps` opcional
* `max_speed_mps` opcional
* `avg_pace_sec_km` opcional
* `avg_cadence` opcional
* `max_cadence` opcional
* `training_effect_aerobic` opcional
* `training_effect_anaerobic` opcional
* `training_load` opcional
* `calories` opcional
* `avg_temperature_c` opcional
* `start_lat` opcional
* `start_lon` opcional
* `device_name` opcional
* `raw_summary_json` opcional
* `created_at`
* `updated_at`

### Restricciones recomendadas

* índice único por `garmin_activity_id`
* índice por `athlete_id + start_time`

---

## 35.11. garmin_activity_lap

Representa cada lap de una actividad.

### Campos sugeridos

* `id`
* `garmin_activity_id_fk`
* `lap_number`
* `lap_type` opcional
  Ejemplo: manual, auto, interval, unknown
* `start_time`
* `duration_sec`
* `moving_duration_sec` opcional
* `distance_m` opcional
* `elevation_gain_m` opcional
* `elevation_loss_m` opcional
* `avg_hr` opcional
* `max_hr` opcional
* `avg_power` opcional
* `max_power` opcional
* `avg_speed_mps` opcional
* `avg_pace_sec_km` opcional
* `avg_cadence` opcional
* `max_cadence` opcional
* `time_in_hr_z1_sec` opcional
* `time_in_hr_z2_sec` opcional
* `time_in_hr_z3_sec` opcional
* `time_in_hr_z4_sec` opcional
* `time_in_hr_z5_sec` opcional
* `time_in_power_z1_sec` opcional
* `time_in_power_z2_sec` opcional
* `time_in_power_z3_sec` opcional
* `time_in_power_z4_sec` opcional
* `time_in_power_z5_sec` opcional
* `stroke_count` opcional
* `swolf` opcional
* `raw_lap_json` opcional
* `created_at`
* `updated_at`

### Restricción recomendada

* índice único por `garmin_activity_id_fk + lap_number`

---

## 35.12. daily_health_metric

Representa el estado fisiológico diario.

### Campos sugeridos

* `id`
* `athlete_id`
* `metric_date`
* `sleep_hours` opcional
* `sleep_score` opcional
* `deep_sleep_min` opcional
* `rem_sleep_min` opcional
* `awake_count` opcional
* `stress_avg` opcional
* `stress_max` opcional
* `high_stress_duration_min` opcional
* `body_battery_start` opcional
* `body_battery_min` opcional
* `body_battery_end` opcional
* `hrv_status` opcional
* `hrv_avg_ms` opcional
* `resting_hr` opcional
* `avg_daily_hr` opcional
* `recovery_time_hours` opcional
* `vo2max` opcional
* `spo2_avg` opcional
* `respiration_avg` opcional
* `raw_health_json` opcional
* `created_at`
* `updated_at`

### Restricción recomendada

* índice único por `athlete_id + metric_date`

---

## 35.13. activity_weather

Representa el clima asociado a una actividad.

### Campos sugeridos

* `id`
* `garmin_activity_id_fk`
* `provider_name`
* `temperature_start_c` opcional
* `apparent_temperature_start_c` opcional
* `humidity_start_pct` opcional
* `dew_point_start_c` opcional
* `wind_speed_start_kmh` opcional
* `wind_direction_start_deg` opcional
* `pressure_start_hpa` opcional
* `precipitation_start_mm` opcional
* `temperature_min_c` opcional
* `temperature_max_c` opcional
* `wind_speed_avg_kmh` opcional
* `precipitation_total_mm` opcional
* `raw_weather_json` opcional
* `created_at`
* `updated_at`

### Restricción recomendada

* índice único por `garmin_activity_id_fk`

---

## 35.14. analysis_report

Representa un informe de análisis.

### Uso

Debe poder servir para:

* análisis individual de sesión
* análisis de actividad suelta
* análisis combinado de grupo
* análisis resumen del día

### Campos sugeridos

* `id`
* `athlete_id`
* `report_type`
  Ejemplo: session, activity, group, day_summary, multisport_event
* `training_day_id` opcional
* `session_group_id` opcional
* `planned_session_id` opcional
* `garmin_activity_id_fk` opcional
* `title`
* `overall_score` opcional
* `overall_status` opcional
  Ejemplo: correct, partial, not_completed, review
* `summary_text` opcional
* `recommendation_text` opcional
* `analysis_context_json` opcional
* `generated_at`
* `created_at`
* `updated_at`

---

## 35.15. analysis_report_item

Representa detalles internos del informe.

### Campos sugeridos

* `id`
* `analysis_report_id`
* `item_order`
* `item_type`
  Ejemplo: warmup, interval, recovery, cooldown, lap, transition, segment, note
* `reference_label` opcional
* `planned_value_text` opcional
* `actual_value_text` opcional
* `item_score` opcional
* `item_status` opcional
* `comment_text` opcional
* `created_at`
* `updated_at`

---

## 36. Relaciones mínimas recomendadas

### Relación central del plan

* `training_plan` 1:N `training_day`
* `training_day` 1:N `planned_session`
* `session_group` 1:N `planned_session`
* `planned_session` 1:N `planned_session_step`

### Relación central de actividades

* `garmin_activity` 1:N `garmin_activity_lap`
* `garmin_activity` 1:1 `activity_weather`

### Relación de matching

* `planned_session` 0..1 : N `garmin_activity` no conviene
* mejor: cada `garmin_activity` puede apuntar a una `planned_session`

Esto evita complejidad innecesaria para el MVP.

### Relación de análisis

* `analysis_report` 1:N `analysis_report_item`
* `analysis_report` puede apuntar opcionalmente a:

  * una sesión
    n  - una actividad
  * un grupo
  * un día

---

## 37. Decisiones de simplificación para el MVP

Para que el proyecto arranque bien, conviene no modelar demasiado pronto ciertas complejidades.

### Sí incluir desde el inicio

* múltiples sesiones por día
* grupos de sesiones
* múltiples actividades por día
* actividad multideporte marcada con bandera
* análisis individual y combinado

### No complicar todavía con

* tabla separada de transiciones reales
* tabla separada de segmentos internos de una actividad multideporte única
* series temporales punto por punto
* múltiples atletas

Si más adelante hace falta, esas extensiones se pueden agregar.

---

## 38. Campos que conviene indexar

### Índices importantes

* `training_day.day_date`
* `planned_session.training_day_id`
* `planned_session.session_group_id`
* `planned_session.sport_type`
* `garmin_activity.start_time`
* `garmin_activity.planned_session_id`
* `garmin_activity.session_group_id`
* `daily_health_metric.metric_date`
* `analysis_report.report_type`

Esto mejora búsquedas de calendario, matching y análisis.

---

## 39. Campos enum o catálogos recomendados

Conviene manejar como enum controlados:

* `sport_type`
* `discipline_variant`
* `event_type`
* `day_type`
* `group_type`
* `session_type`
* `step_type`
* `report_type`
* `overall_status`
* `item_type`
* `item_status`

Esto hace el sistema más consistente y predecible para análisis y UI.

---

## 40. Resumen del esquema inicial

La base de datos inicial quedará centrada en estas piezas:

### Perfil y contexto

* athlete
* athlete_hr_zone
* athlete_power_zone
* daily_health_metric

### Planificación

* goal
* training_plan
* training_day
* session_group
* planned_session
* planned_session_step

### Ejecución real

* garmin_activity
* garmin_activity_lap
* activity_weather

### Análisis

* analysis_report
* analysis_report_item

Este esquema ya permite construir un MVP serio, con soporte para:

* sesión simple
* intervalos por laps
* doble turno
* brick
* duatlón
* triatlón
* contexto fisiológico
* contexto climático
* análisis individual y combinado

---

## 41. Próximo paso recomendado

Con este esquema definido, el siguiente paso será redactar el primer prompt técnico para Codex.

Ese prompt debe pedir solamente:

* creación del esqueleto del proyecto
* configuración inicial de FastAPI
* estructura de carpetas
* modelos SQLAlchemy basados en este esquema
* migración inicial con Alembic
* una página base funcionando

No conviene todavía pedir Garmin, clima ni análisis en el primer disparo.
