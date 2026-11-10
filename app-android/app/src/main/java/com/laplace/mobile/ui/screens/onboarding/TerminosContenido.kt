package com.laplace.mobile.ui.screens.onboarding

/** Términos y Condiciones de Laplace — 2026-09-08.
 *
 * Redactado para un producto de PRONÓSTICO/ANÁLISIS deportivo, nunca una casa de apuestas
 * (regla dura del proyecto, ver `.claude/rules/product-philosophy.md`). No reemplaza asesoría
 * legal profesional formal, pero cubre las secciones estándar de un servicio de este tipo:
 * qué es el servicio (y qué NO es), edad mínima, ausencia de garantía de resultados, límites de
 * responsabilidad, manejo de cuenta/datos, planes y su cancelación, y ley aplicable. Investigado
 * sobre la estructura habitual de T&C de apps de análisis/estadísticas deportivas (disclaimers de
 * "no es asesoría financiera", límite de responsabilidad, edad mínima) — adaptado al caso
 * específico de Laplace, no copiado de ningún servicio real.
 */
object TerminosContenido {
    const val VERSION = "1.0 — 2026-09-08"

    val TEXTO = """
        TÉRMINOS Y CONDICIONES DE USO — LAPLACE
        Versión $VERSION

        1. QUÉ ES LAPLACE

        Laplace es un servicio de pronóstico y análisis estadístico de partidos de fútbol. Genera
        estimaciones de probabilidad (modelos Poisson, Dixon-Coles y un consenso ponderado entre
        varias fuentes de datos) y las presenta junto con la información en la que se basan
        (tabla de posiciones, forma reciente, historial entre los equipos, cuotas de mercado como
        dato de referencia).

        2. LAPLACE NO ES UNA CASA DE APUESTAS

        Laplace NUNCA acepta dinero para apostar, no opera como casa de apuestas ni intermedia
        apuestas de ningún tipo — ni propias, ni entre usuarios, ni hacia terceros. Lo único que
        se ofrece es acceso a pronósticos y a los resultados del análisis estadístico, mediante
        planes de uso (gratuito y de pago con límites de consultas). Ninguna cuota o probabilidad
        mostrada en la aplicación constituye una oferta para apostar — es información de contexto
        para el análisis, nada más. Si buscás un servicio para apostar dinero real, Laplace no es
        ese servicio.

        3. EDAD MÍNIMA

        Debés tener al menos 18 años para crear una cuenta y usar Laplace. Aunque el servicio no
        involucra apuestas, su contenido hace referencia a cuotas y mercados deportivos —
        mantenemos la misma edad mínima que rige para ese tipo de información en la mayoría de
        jurisdicciones, como medida de precaución razonable.

        4. SIN GARANTÍA DE RESULTADOS

        El fútbol es un evento con resultado incierto por naturaleza. Ningún modelo estadístico,
        por bueno que sea, puede garantizar el resultado real de un partido. Los porcentajes de
        confianza y probabilidades que muestra Laplace son estimaciones basadas en datos
        históricos y en tiempo real — no son una promesa ni una garantía de acierto. Laplace
        publica también sus métricas reales de rendimiento (winrate por módulo, cuando hay
        suficientes partidos verificados) precisamente para que puedas evaluar la calidad real del
        sistema en vez de confiar en promesas sin evidencia.

        5. NO ES ASESORÍA FINANCIERA NI DE APUESTAS

        Nada en Laplace constituye asesoría financiera, de inversión, ni una recomendación de
        apostar. Cualquier decisión que tomés con dinero propio, en cualquier plataforma, es
        exclusivamente tu responsabilidad. Laplace no participa ni se beneficia de ninguna
        apuesta que puedas realizar en otro lugar.

        6. TU CUENTA

        Podés registrarte con usuario y contraseña, o de forma automática al usar la app (vía un
        identificador de dispositivo). Sos responsable de mantener tu contraseña segura y de toda
        actividad que ocurra desde tu cuenta. Si sospechás un uso no autorizado, contactanos por
        el canal de soporte indicado en la app.

        7. PLANES Y LÍMITES DE USO

        Laplace ofrece un plan gratuito con límites diarios de consultas, y planes de pago (Pro,
        Max) con límites mayores. Los precios, límites exactos y medios de pago vigentes se
        muestran dentro de la app al momento de contratar — pueden cambiar con aviso razonable.
        Un plan de pago da acceso a más consultas y funciones, nunca a una garantía de acierto
        distinta a la del resto de usuarios.

        8. DATOS QUE GUARDAMOS

        Guardamos lo necesario para operar el servicio: tu usuario (con contraseña protegida,
        nunca en texto plano), tu plan, tu historial de consultas y predicciones, y estadísticas
        de uso. No vendemos tus datos a terceros. Nunca vas a ver de nuevo una contraseña o clave
        ya guardada en ninguna pantalla — solo podés reemplazarla o eliminarla.

        9. CANCELACIÓN Y BAJA

        Podés dejar de usar Laplace en cualquier momento. Si tenés un plan de pago activo, podés
        cancelarlo desde la app — la cancelación aplica desde el próximo período, no genera
        reembolso del período ya iniciado salvo que la ley aplicable indique lo contrario.

        10. LÍMITE DE RESPONSABILIDAD

        Laplace se ofrece "tal cual está". No respondemos por decisiones que tomés basándote en
        sus pronósticos, ni por pérdidas de ningún tipo derivadas de su uso o de la interrupción
        temporal del servicio (mantenimiento, caídas de las fuentes de datos externas, etc.).

        11. CAMBIOS A ESTOS TÉRMINOS

        Podemos actualizar estos términos cuando el servicio cambie de forma relevante. Un cambio
        importante se va a mostrar de nuevo dentro de la app para que lo aceptes otra vez antes de
        seguir usando Laplace.

        12. LEY APLICABLE

        Estos términos se rigen por las leyes de Chile, sin perjuicio de los derechos que te
        correspondan como consumidor bajo la ley de tu país de residencia.

        Al marcar "Acepto los Términos y Condiciones" confirmás que leíste este documento, que
        tenés al menos 18 años, y que entendés que Laplace es un servicio de pronóstico y
        análisis — nunca una casa de apuestas.
    """.trimIndent()
}
