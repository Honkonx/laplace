package com.laplace.mobile.navigation

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.laplace.mobile.data.local.AuthManager
import com.laplace.mobile.ui.theme.accent
import com.laplace.mobile.ui.theme.bg
import com.laplace.mobile.ui.theme.border
import com.laplace.mobile.ui.theme.green
import com.laplace.mobile.ui.theme.surfaceLight
import com.laplace.mobile.ui.theme.text
import com.laplace.mobile.ui.theme.textMuted

@Composable
fun DrawerContent(navController: NavController) {
    val activePlan = AuthManager.planState.uppercase()
    val badgeColor = when (activePlan) {
        "MAX" -> green
        "PRO" -> accent
        else -> textMuted
    }
    ModalDrawerSheet(
        drawerContainerColor = bg,
        modifier = Modifier.fillMaxWidth(0.75f),
    ) {
        Column(
            modifier = Modifier.padding(vertical = 48.dp)
        ) {
            Row(
                modifier = Modifier.padding(horizontal = 24.dp, vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "Laplace",
                    color = text,
                    style = MaterialTheme.typography.headlineLarge,
                )
                Spacer(Modifier.width(10.dp))
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(12.dp))
                        .background(surfaceLight)
                        .padding(horizontal = 10.dp, vertical = 4.dp),
                ) {
                    Text(
                        text = "PLAN $activePlan",
                        color = badgeColor,
                        fontWeight = FontWeight.Bold,
                        style = MaterialTheme.typography.labelSmall,
                    )
                }
            }
            Text(
                text = "Predicciones deportivas IA",
                color = textMuted,
                modifier = Modifier.padding(horizontal = 24.dp),
                style = MaterialTheme.typography.bodyMedium,
            )
            Spacer(Modifier.height(32.dp))
            HorizontalDivider(color = border)
            Spacer(Modifier.height(8.dp))

            DrawerItem("Perfil", Screen.Profile, navController)
            DrawerItem("Historial", Screen.History, navController)
            DrawerItem("Código Activación", Screen.CodigoActivacion, navController)
            DrawerItem("Mejorar Plan", Screen.Upgrade, navController)
            DrawerItem("Tema", Screen.ConfigTheme, navController)
            DrawerItem("Log", Screen.Log, navController)
            DrawerItem("Acerca de", Screen.About, navController)
        }
    }
}

@Composable
private fun DrawerItem(label: String, screen: Screen, navController: NavController) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clickable { navController.navigate(screen) { launchSingleTop = true } }
            .padding(horizontal = 24.dp, vertical = 14.dp)
    ) {
        Text(label, color = text, style = MaterialTheme.typography.titleMedium)
    }
}
