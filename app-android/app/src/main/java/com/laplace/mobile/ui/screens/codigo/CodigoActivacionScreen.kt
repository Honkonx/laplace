package com.laplace.mobile.ui.screens.codigo

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import kotlinx.coroutines.launch
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.laplace.mobile.data.remote.LaplaceApi
import com.laplace.mobile.ui.theme.*
import com.laplace.mobile.data.local.PreferencesManager

@Composable
fun CodigoActivacionScreen(navController: NavController) {
    var code by remember { mutableStateOf("") }
    var loading by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf<String?>(null) }
    var successPlan by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val currentNickname = remember { PreferencesManager.nickname }

    val formatted = remember(code) {
        val clean = code.replace(Regex("[^A-Z0-9]"), "")
        buildString {
            clean.forEachIndexed { i, c ->
                if (i == 3 || i == 8) append('-')
                append(c)
            }
        }.take(15)
    }

    Column(
        modifier = Modifier.fillMaxSize().background(bg).padding(20.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(Modifier.height(48.dp))
        Text("Codigo Activacion", style = MaterialTheme.typography.headlineLarge, color = text, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(8.dp))
        Text("Ingresa tu codigo KS-PRO-XXXXXXX", style = MaterialTheme.typography.bodyMedium, color = textMuted, textAlign = TextAlign.Center)
        Spacer(Modifier.height(32.dp))

        OutlinedTextField(
            value = formatted,
            onValueChange = { code = it.uppercase().filter { c -> c.isLetterOrDigit() || c == '-' } },
            label = { Text("Codigo") },
            placeholder = { Text("KS-PRO-XXXXXXX") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Characters, imeAction = ImeAction.Done),
            keyboardActions = KeyboardActions(onDone = {}),
            modifier = Modifier.fillMaxWidth(),
            colors = OutlinedTextFieldDefaults.colors(
                focusedTextColor = text,
                unfocusedTextColor = text,
                cursorColor = accent,
                focusedBorderColor = accent,
                unfocusedBorderColor = border,
                focusedLabelColor = accent,
                unfocusedLabelColor = textMuted,
            ),
        )

        Spacer(Modifier.height(24.dp))

        Button(
            onClick = {
                if (formatted.length < 12) {
                    message = "El codigo debe tener formato KS-PRO-XXXXXXX"
                    successPlan = null
                    return@Button
                }
                loading = true
                message = null
                scope.launch {
                    try {
                        val resp = LaplaceApi.callWebhook(
                            action = "activar_codigo",
                            params = mapOf("codigo" to formatted, "nickname" to currentNickname),
                        )
                        val data = resp.data ?: emptyMap()
                        val ok = (data["activado"] as? Boolean) ?: (data["success"] as? Boolean) ?: false
                        if (ok) {
                            val nuevoPlan = (data["plan"] as? String)?.uppercase() ?: "PRO"
                            successPlan = nuevoPlan
                            com.laplace.mobile.data.local.AuthManager.plan = nuevoPlan
                            message = (data["mensaje"] as? String)
                                ?: (data["message"] as? String)
                                ?: "Codigo activado correctamente!"
                        } else {
                            successPlan = null
                            message = (data["mensaje"] as? String)
                                ?: (data["message"] as? String)
                                ?: (data["error"] as? String)
                                ?: "Codigo invalido"
                        }
                    } catch (_: Exception) {
                        successPlan = null
                        message = "Error de conexion"
                    } finally {
                        loading = false
                    }
                }
            },
            enabled = !loading && formatted.length >= 12,
            colors = ButtonDefaults.buttonColors(containerColor = accent, contentColor = text, disabledContainerColor = surface),
            modifier = Modifier.fillMaxWidth().height(50.dp),
            shape = RoundedCornerShape(12.dp),
        ) {
            if (loading) {
                CircularProgressIndicator(color = text, modifier = Modifier.size(22.dp), strokeWidth = 2.dp)
            } else {
                Text("Activar", fontWeight = FontWeight.SemiBold)
            }
        }

        Spacer(Modifier.height(16.dp))

        message?.let {
            Text(
                it,
                color = if (successPlan != null) green else red,
                style = MaterialTheme.typography.bodyMedium,
                textAlign = TextAlign.Center,
            )
        }

        successPlan?.let { plan ->
            Spacer(Modifier.height(12.dp))
            val planColor = when (plan) {
                "MAX" -> green
                else -> accent
            }
            Box(
                modifier = Modifier
                    .clip(RoundedCornerShape(20.dp))
                    .background(planColor.copy(alpha = 0.15f))
                    .padding(horizontal = 20.dp, vertical = 8.dp),
            ) {
                Text(
                    plan,
                    color = planColor,
                    fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.titleLarge,
                )
            }
        }
    }
}
