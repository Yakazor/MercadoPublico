# Disparador de actualización

Cambiar `actualizar.txt` (y hacer push a `feature/api-mercadopublico`) lanza los
workflows «Radar diario de licitaciones» y «Órdenes de compra históricas». Lo usa
la rutina de Claude cuando se aprieta «Actualizar ahora» en el dashboard, porque
esa sesión no tiene acceso a la API de GitHub para disparar workflows.
