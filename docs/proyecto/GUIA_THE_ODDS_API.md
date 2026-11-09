# The Odds API como precio de referencia (BE-012) — guía del dueño

*9-nov-2026. Estado: el conector está escrito y **apagado**. No hay clave, no hay tarea programada y no se hace ninguna petición. Esta guía dice qué hay que hacer a mano para encenderlo, y qué no se debe hacer sin decidirlo antes.*

## Para qué sirve

Un precio «eficiente» (el de Pinnacle, que The Odds API lista en la región `eu`) con el margen quitado por el mismo método Shin que usa el resto de la plataforma. Sirve de vara de medir **interna**: el valor de cierre (CLV) de los picks y la comprobación de que una ventaja no es un error del libro. No es una fuente de cuotas para el usuario y no se enseña ni se enlaza ningún operador desde ella.

## Qué hay en el código

`backend/src/fbi/providers/the_odds_api/`:

- `settings.py`: la configuración. Sin `FBI_THEODDSAPI_KEY` el conector está apagado y el cliente **no se puede construir**. Solo existe el plan `free`; el presupuesto mensual por defecto es el 90 % del plan (450 de 500 créditos) y no puede pasar de 500.
- `client.py`: una llamada (`h2h`, región `eu`) cuesta 1 crédito. Cuenta los créditos antes (y se niega a pasar del presupuesto o de lo que el proveedor dice que queda) y después (lo que el proveedor cobró). La clave **solo** viaja como parámetro `apiKey` de la dirección —el proveedor no admite otra forma—, así que ninguna dirección se escribe en un registro y un error de red se relanza sin la excepción que la contiene.
- `parse.py`: del JSON del proveedor a precios exactos (`Decimal`); un libro con el 1X2 mal formado se descarta y se anota por qué.
- `identity.py`: a qué partido nuestro corresponde un evento: local con local, visitante con visitante (nunca al revés), nombres parecidos, saque inicial a menos de 2 horas y **un solo** partido que cumpla; con dudas, no hay precio.

Nada lo llama todavía: conectarlo a una tarea (con un almacén de créditos persistente, una fila por mes) es el siguiente paso y no se da sin tu clave.

## Lo que tienes que hacer tú (y solo si quieres encenderlo)

1. Abre una cuenta **gratuita** en https://the-odds-api.com con tu correo (500 créditos al mes; no pide tarjeta). No contrates ningún plan de pago: costaría desde 30 USD al mes y es una decisión tuya que no se toma por defecto ni por configuración.
2. Copia la clave en un archivo de tu portátil (por ejemplo `fbi_scratch\the_odds_api_key.txt`), **sin pegarla en el chat**. Avísame y la subo al servidor sin imprimirla, a `app.env` como `FBI_THEODDSAPI_KEY`, y tomo la línea base de configuración (`predigolctl config-baseline`).
3. Aun con la clave puesta no pasa nada hasta que una tarea lo llame; esa tarea se prepara y se prueba antes (con los 500 créditos de prueba, que alcanzan para validar unos pocos partidos).

## Aviso legal (revisión pendiente)

Los precios de operadores no autorizados en Colombia solo se usan como referencia interna (Circular MinTIC 0017/2025, Coljuegos). Sin enlaces, sin promoción y sin nombrar al operador en el producto. Antes de mostrar nada de esto a un usuario, revisión legal.

## Qué cambia en la arquitectura

`football-data.co.uk` sale de la arquitectura objetivo: sus condiciones prohíben el uso comercial y el entrenamiento de modelos. No se descarga nada nuevo de ahí; qué hacer con lo ya importado lo decides tú.
