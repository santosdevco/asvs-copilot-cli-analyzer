=== COMPONENT SEMANTIC CONTEXT: [Nombre del Componente] ===
[ARCHITECTURAL ROLE]: (Ej: Punto de entrada de autenticación y gestión de identidad)
[DATA INPUTS]: (Ej: req.body.user, req.body.password, headers['X-Company-ID'])
[DATA OUTPUTS]: (Ej: JWT Token, Cookies HttpOnly, Redirección a /dashboard)
[INTERACTIONS]: (Ej: Consulta tabla 'users', escribe en 'login_logs')
[STATE MANAGEMENT]: (Ej: Usa express-session persistido en MongoDB)

[BUSSINESS LOGIC]: Reglas de negocio mas importantes

[ACCESS CONTROL & ROLES]    Ejemplo: Endpoints públicos (/login, /register). Requiere rol 'Admin' para rutas de borrado. Validado vía middleware 'checkAdmin'

[TRUST BOUNDARIES] Ejemplo: Los datos del cliente pasan directamente de la API Gateway a la base de datos sin una capa de sanitización intermedia (DTOs).
