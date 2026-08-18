# Reglas del dinero y del acceso

Las reglas que gobiernan el cobro y la entrega en este bot no se deducen
leyendo el código: se descubren rompiéndolas. Este documento las recoge, con
el fallo concreto que enseñó cada una, para que nadie tenga que volver a
descubrirlas en producción.

No es documentación de arquitectura (para eso están los otros `.md`). Es la
lista de cosas que parecen correctas, se escriben en un minuto, y hacen daño.

---

## 1. Los recursos del SDK de Stripe no son diccionarios

En stripe 15.x, `subscription.get("status")` lanza `AttributeError`, y el
texto de esa excepción es solo `"get"`. Y `dict(objeto)` tampoco funciona.

**Qué pasó:** la autoconfiguración del webhook llevaba tiempo fallando en
producción con el mensaje `error comprobando la configuración: get`, imposible
de diagnosticar sin reproducirlo. El mismo patrón, en el camino de cobro,
habría roto **todos** los pagos.

**La regla:** todo lo que venga del SDK pasa por `recurso_plano()`
(`group_subscription_service.py`) antes de tocarse. En el webhook, el evento se
lee con `json.loads(payload)` después de que `stripe.Webhook.construct_event`
verifique la firma.

**En los tests:** los dobles se construyen con `construct_from`, no con
diccionarios. Un doble más permisivo que producción es un test que da permiso
para desplegar un fallo.

---

## 2. La rama específica va SIEMPRE antes que su prefijo

`data.startswith("mysub_stoprenew_")` escrito antes de
`data.startswith("mysub_stoprenew_go_")` deja el segundo botón muerto. No hay
error: el botón simplemente hace otra cosa.

**Qué pasó:** dos veces. Un `section == "security"` duplicado y la pareja
`stoprenew` / `stoprenew_go`.

**La regla:** en cada cadena de `if`, la condición más específica primero. Las
comparaciones `==` son seguras entre sí; los `startswith` no.

**Está vigilado:** `tests/test_unreachable_branches.py` recorre las cadenas del
router y falla si una rama anterior que corta el flujo deja muerta a otra. Ese
test lleva dos pruebas sobre sí mismo, porque una red que se queda ciega sin
avisar es peor que no tener red.

---

## 3. Marcar primero, enviar después

Los proveedores reintentan los webhooks. Enviar y luego marcar significa
enviar dos, cinco o veinte veces el mismo aviso.

**La regla:** el registro (`INSERT ... ON CONFLICT DO NOTHING` con clave
única) va **antes** del envío, y solo se envía si el registro fue nuevo.

**La excepción importante:** cuando el aviso protege el acceso de alguien
—como los avisos de cobro fallido—, un error de base de datos al marcar se
resuelve **enviando**. Mejor un mensaje repetido que un cliente que pierde el
acceso sin haberse enterado. Cuando el riesgo es al contrario (spam que gana
un bloqueo), el fallo al marcar se resuelve **callando**.

---

## 4. Quien ya está suscrito conserva su precio

La suscripción de Stripe guarda su propio `Price`. Subir el precio de un plan
solo afecta a altas nuevas, y eso es lo correcto.

**La regla:** nada en el repositorio modifica `items` ni `price` de una
suscripción existente. Los únicos `Subscription.modify` permitidos son:

| Uso | Por qué es legítimo |
|---|---|
| `cancel_at_period_end` | el interruptor de renovación del comprador |
| `discounts=` | oferta de salvamento: solo puede MEJORAR su precio |
| `pause_collection` | pausa: suspende cobros sin tocar el precio |
| `trial_end` | días de regalo de un referido: RETRASA el cargo |

**Está vigilado:** un test recorre todos los `Subscription.modify` del
repositorio y falla si aparece uno que no sea de esa lista, o que toque
`items`/`price`.

---

## 5. Pedir una devolución y procesarla son dos cosas

`refund_service` procesa la devolución que **ya ocurrió** (webhook): marca el
pago, retira el acceso, revoca enlaces, expulsa y avisa.
`refund_request_service` solo se la **pide** a Stripe.

**El error que evita esa separación:** si al pedir la devolución se marcara el
pago como `refunded` —que es lo primero que uno escribe—, el webhook lo vería
ya marcado, se lo saltaría por idempotencia, y **nadie retiraría el acceso ni
avisaría al comprador**. Se devuelve el dinero y el cliente se queda dentro.

**La regla:** la idempotencia de la petición vive en su propia tabla
(`refund_requests`), no en el estado del pago. Y si Stripe rechaza, la marca se
borra: si no, ese cobro quedaría imposible de devolver para siempre.

---

## 6. Cuatro formas de pagar y no recibir nada

Todas tienen ya salida automática. Si aparece una quinta, este es el patrón a
seguir:

| Fallo | Quién lo resuelve |
|---|---|
| Webhook del alta perdido | repaso nocturno con Stripe (`stripe_reconcile_service`) |
| Expulsado o salido por error | enlace nuevo al detectarlo (`member_recovery_service`, desde Guardian) |
| Cobro que no pudo convertirse en acceso | botón en el aviso al propietario (`incident_repair_service`) |
| Avería de permisos del bot | al recuperarse, enlace a los que se quedaron sin él |

**La regla que comparten:** el bot repara solo lo que se puede reparar **sin
criterio** (poner un ancla que falta, mandar un enlace, soltar un ancla
muerta). Para lo demás pone el botón delante de quien tiene el criterio, con
el permiso comprobado **al pulsar** —un callback se puede reenviar— y sin
escribir un pago falso que desvirtúe los ingresos del propietario.

Aparecieron dos más, y las dos se **evitan** en vez de repararse, porque el
fallo estaba antes del cobro: un plan cuya duración no se puede entregar
(sección 12) y una credencial de webhook que no se puede verificar (sección
13). Cuando se puede saber ANTES de cobrar que no se va a poder entregar, la
salida no es una reparación: es no cobrar.

---

## 7. Un número que exagera es peor que no tener número

**Qué pasó:** el panel global tenía tres mentiras de dinero a la vez: contaba
devoluciones como ingreso, mezclaba monedas bajo `MAX(currency)` y mostraba
céntimos como si fueran unidades (`1500 EUR` por 15 euros).

**Las reglas de todas las pantallas de negocio:**

- Solo cuenta como ingreso lo que está en `('paid', 'completed')`. Una
  devolución tiene su propia línea.
- Los importes de `payments` van en **céntimos**; se dividen al mostrarlos.
- Las monedas no se mezclan: se agrupa por moneda.
- **Sin base no hay porcentaje.** Con cero visitas no se muestra «0% de
  conversión», se dice «todavía no hay dato». Con menos de diez visitas no se
  diagnostica nada, porque cualquier diagnóstico ahí es ruido.
- La vida media del cliente se mide solo sobre quienes **ya terminaron**:
  incluir a los activos, que siguen sumando días, la hunde y miente a la baja.
- Un tope de lista dice cuántos se calla («…y 3 más»). Un tope silencioso se
  lee como «esto es todo».

---

## 8. Los tests que mienten

**Qué pasó:** dos veces, una tabla nueva sin añadir a la lista de limpieza de
`conftest`. La suite no se rompió: pasó **estando mal**. Una prueba de «no se
crean cupones duplicados» pasaba con duplicados dentro.

**Las reglas:** toda tabla en la que escriba un test se limpia entre pruebas, y
quien cuente eventos de auditoría borra los suyos antes (esa tabla se conserva
a propósito).

**Está vigilado:** `tests/test_db_isolation.py`, con lista de excepciones que
exige motivo escrito y comprueba que las excepciones sigan siendo reales.

---

## 9. Un texto que falta se le enseña al comprador

`t()` devuelve la clave cuando no la encuentra: correcto en producción (mejor
un texto raro que un bot caído) y silencioso hasta que un cliente recibe
`mysub.btn_recepits`.

**La regla:** las claves literales usadas en el código tienen que existir en el
catálogo, y las familias de clave calculada (etapas del aviso de cobro
fallido, motivos del cambio de plan, secciones de ayuda) están protegidas a
mano en `tests/test_i18n_keys_exist.py`, con el motivo delante de cada grupo.

**Lo que NO se puede exigir:** que toda clave del catálogo aparezca como
literal. Al comprobarlo salían 20 «muertas» que se usan con clave dinámica;
hacerle caso habría borrado textos vivos.

---

## 10. Activaciones que dependen del panel de Stripe

Tres funciones están escritas, probadas y **dormidas**, porque exigen una
activación de una sola vez en el panel de Stripe. Encender la bandera sin
hacer la activación no degrada: **rompe**.

| Función | Qué falta | Qué pasa si se enciende sin activar |
|---|---|---|
| Customer Portal | activarlo en Stripe → Portal de cliente | el botón de cambiar tarjeta no aparece (degrada, no rompe) |
| Stripe Connect | activar Connect en la cuenta de la plataforma | el alta del creador no se puede empezar |
| Stripe Tax | Tax → registros de países, y `STRIPE_TAX_ENABLED=true` | `Session.create` falla: **se caen todos los cobros** |

El coste de tener el portal apagado se mide solo: el panel de salud de
comunidades cuenta cuántos avisos de cobro fallido salieron sin botón para
cambiar la tarjeta.

---

## 11. Las tres herramientas del arnés

Mover código en un bot de cientos de botones sin romper pantallas no se hace
con cuidado: se hace con instrumentos.

| Herramienta | Dónde | Cuándo |
|---|---|---|
| Barrido de botones | `tests/test_button_sweep.py` | en cada PR, automático |
| Ramas inalcanzables | `tests/test_unreachable_branches.py` | en cada PR, automático |
| Retrato de pantallas (golden master) | `tools/snapshot.py` + `tools/snapshot_diff.py` | a mano, antes y después de un cambio grande |

Las dos primeras son tests porque no necesitan mantenimiento. La tercera **no
lo es a propósito**: exigiría un retrato de referencia versionado, que habría
que regenerar en cada cambio intencionado de texto, y esa fricción acaba en
alguien regenerándolo sin mirar — lo contrario de para lo que sirve.

Uso del retrato:

```bash
TEST_DATABASE_URL=... python tools/snapshot.py /tmp/antes.json
# ...el cambio...
TEST_DATABASE_URL=... python tools/snapshot.py /tmp/despues.json
python tools/snapshot_diff.py /tmp/antes.json /tmp/despues.json
```

**La única regla al leer el diff:** cada diferencia tiene que ser una que
esperabas. La que no esperabas es el fallo que ibas a desplegar. Con estas
tres se troceó una función de 24.000 líneas en 36 módulos sin mover una sola
pantalla.

---

## 12. Nunca se ofrece lo que el cobro va a rechazar

**Qué pasó:** la línea de arranque que informa del escaparate leyó producción y
dijo: `1 comunidad(es) vendible(s), la más barata a 7 EUR/1300000 días`. La
ÚNICA comunidad vendible del sistema tenía un plan de 1.300.000 días, y
`calculate_group_access_expiration` se niega a convertir en acceso cualquier
duración por encima de 3.650: registraba el error, abría incidencia y devolvía
OK. Lo único que se podía comprar era justo lo único que no se podía entregar.

**La regla:** el límite de lo entregable vive en UN sitio
(`MAX_PLAN_DURATION_DAYS`, en `payment_access_service`, al lado de la función
que decide el acceso) y lo importan todos: el webhook, el escaparate, el panel
del propietario y las alertas. La diferencia entre el número que usa quien
OFRECE y el que usa quien ENTREGA es exactamente el hueco por el que se cobra
sin entregar.

**La asimetría que decide los casos raros:** `duration_days = 0` significa
acceso permanente para la concesión, así que parece vendible. No se vende,
porque ningún asistente del bot puede crear un plan con 0 —todos exigen entre 1
y el techo— y un 0 en la tabla es un dato anómalo, no una decisión. Venderlo por
error regala acceso de por vida al precio de un mes y no se deshace; no venderlo
deja un plan sin usar y el panel lo dice. Cuando los dos errores no cuestan lo
mismo, se elige el reversible.

**Y dejar de ofrecer algo roto no puede volverlo invisible:** al esconderlo, esa
comunidad deja de vender EN SILENCIO. Un fallo ruidoso convertido en silencioso
solo es una mejora si alguien avisa, así que lo dicen tres sitios: el arranque,
el panel «🚦 ¿Puedo vender?» y una alerta al propietario con el número exacto y
qué escribir.

---

## 13. Un campo que solo se comprueba «no vacío» no está comprobado

**Qué pasó:** la casilla del `webhook_id` de PayPal guardaba un valor con forma
de `client_id`. Lo único que se validaba era que no estuviera vacío. El cobro
salía, PayPal lo aceptaba, el comprador pagaba, y la verificación de la firma
del webhook contestaba HTTP 400: cobrado, no entregado, sin traza. Y la
comprobación periódica lo llamaba «no se ha podido leer la configuración», que
manda a revisar TODAS las credenciales cuando el problema es un campo y se sabe
cuál.

**La regla:** una credencial de la que depende la ENTREGA se valida por forma
antes de guardarse, y quien vaya a cobrar con ella se niega si no la pasa. Y el
diagnóstico nombra el campo: decir «revisa tus credenciales» cuesta una tarde,
decir «el webhook_id no puede ser esto, el tuyo está en Apps & Credentials →
Webhooks» cuesta un minuto.

**La otra mitad de la regla, igual de importante:** el filtro se queda en lo
IMPOSIBLE, no en lo esperado. Rechazar una credencial válida deja a un
propietario sin poder cobrar, que es peor que el fallo que se evita. Aquí se
descarta lo que ninguna credencial de webhook puede ser (más de 40 caracteres,
espacios, trozos de URL) y se aceptan los guiones, porque no se puede afirmar
que PayPal no los use nunca. La primera versión exigía `[A-Za-z0-9]` y rompió
tres pruebas existentes que usaban `WH-1`: avisaron de que el filtro era
demasiado estricto antes de que lo fuera en producción.
