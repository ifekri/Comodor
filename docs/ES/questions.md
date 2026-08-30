# Preguntas

La ambigüedad tiene dos malos finales. El agente elige una lectura, construye lo
equivocado, y te cuesta un ciclo de revisión. O pregunta en prosa, una pregunta
a la vez, y gastas cuatro turnos en resolver lo que se podía resolver en una
pantalla.

Comodor toma una tercera vía. Cuando una petición puede leerse de más de una
manera, el agente calcula *todo* lo que no tiene claro primero, y luego te lo
plantea como un formulario corto de opción múltiple — tres o cuatro preguntas,
respondidas en unos quince segundos, antes de escribir una línea.

Al pedirle "añade rate limiting al servidor web", leyó diez archivos y luego
preguntó esto:

```
┏━  3 questions  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                                                                          ┃
┃    ☐  Client identity   ☐  Over-limit   ☐  Scope                         ┃
┃                                                                          ┃
┃  How should clients be identified for rate limiting?                     ┃
┃                                                                          ┃
┃   › ☐ By IP address (recommended)                                        ┃
┃        The server already reads client_address for the loopback check.   ┃
┃     ☐ By token                                                           ┃
┃     ☐ Something else                                                     ┃
┃                                                                          ┃
┃    0 of 3 answered                                                       ┃
┃                                                                          ┃
┗━━━━━━━━━━━━━━  ↑↓ move · ←→ question · space pick · enter next · esc  ━━┛
```

Fíjate en la segunda línea de la primera opción. Ya había leído `web/server.py`
antes de preguntar, y la pregunta es sobre la decisión que esa lectura no pudo
resolver.

## En la terminal

```
left / right      previous and next question
up / down         move within the options
space             pick — and toggle, when several answers may apply
enter             pick, then jump to the next unanswered question;
                  on the last one, send
ctrl+s            send from anywhere
escape            close without answering
```

La tira de pestañas lleva una marca por pregunta, así que de un vistazo ves
cuáles siguen pendientes sin visitar cada una.

## En el navegador

El mismo formulario como un diálogo. Haz clic en las pestañas o usa las
flechas, haz clic en una opción, y pulsa **Send**. `Escape` lo cierra.

## La última fila

Cada pregunta termina con **Something else** y una caja para escribir. La añade
Comodor, no el modelo, y el modelo no puede quitarla — el punto entero de la
fila es que cubre lo que el modelo no logró pensar. Escribir en ella reemplaza
la opción que estuviera seleccionada, y elegir una opción borra lo escrito, así
que una pregunta nunca vuelve con dos respuestas en conflicto.

## Saltar

Enviar un formulario con preguntas sin responder está bien, y no es lo mismo
que descartarlo. Al agente se le dice exactamente cuáles dejaste intactas, y
que por tanto no las restringiste — así que decide esas por su cuenta y te dice
por dónde fue.

Descartar el formulario por completo (**Not now**, o `escape`) le dice al
agente que siga con valores por defecto sensatos y que **no vuelva a
preguntar**. Un segundo formulario puesto a alguien que acaba de cerrar el
primero es el comportamiento que hace odiar una función así.

## Cuando no pregunta

Por diseño, no por accidente:

- Cualquier cosa que pudiera averiguar leyendo el proyecto. Lee primero.
- Permiso para continuar. Para eso está el aviso de aprobación.
- Confirmarte su plan.
- Una decisión con un valor por defecto obvio. Toma el valor por defecto y te
  dice que lo hizo.

## Límites

Como máximo cuatro preguntas, y como máximo cuatro opciones cada una — más la
fila de escribe-la-tuya, que no gasta una de las cuatro. Más que eso deja de
ser un formulario rápido y se convierte en una entrevista, y un agente que
necesita seis respuestas debería pedir las cuatro que importan y resolver el
resto.

El formulario espera treinta minutos. Después vuelve sin responder y el agente
sigue, así que un formulario abierto en una máquina donde no hay nadie no puede
mantener una ejecución abierta indefinidamente.

## Para otros modelos

La herramienta se llama `ask` y es `SAFE`, lo que significa que también está
disponible en modo plan — planificar es cuando la ambigüedad muerde más fuerte.

Con cuánta facilidad un modelo recurre a ella varía. Todos los modelos probados
preguntan cuando la petición claramente lo necesita y se quedan callados cuando
no, pero si el tuyo está construyendo sobre una suposición, decir *"pregúntame
cualquier cosa que necesites decidir primero"* en tu propio mensaje lo resuelve
de inmediato.
