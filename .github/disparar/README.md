# Disparador de actualización

Cambiar `actualizar.txt` (y hacer push a `feature/api-mercadopublico`) lanza los
workflows «Radar diario de licitaciones», «Órdenes de compra históricas» y «Compras Ágiles». Lo usa
la rutina de Claude cuando le pides «actualiza el radar», porque
esa sesión no tiene acceso a la API de GitHub para disparar workflows.
