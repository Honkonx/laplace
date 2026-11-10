package com.laplace.mobile.ui.screens.notifications

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.navigation.NavController
import com.laplace.mobile.data.local.PreferencesManager
import com.laplace.mobile.navigation.Screen
import com.laplace.mobile.ui.theme.*

@Composable
fun NotificationPermissionScreen(navController: NavController) {
    val context = LocalContext.current
    var showRationale by remember { mutableStateOf(false) }

    val requestPermissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { _ ->
        PreferencesManager.notificationsAsked = true
        navController.navigate(Screen.Home) {
            popUpTo(Screen.Onboarding) { inclusive = true }
        }
    }

    LaunchedEffect(Unit) {
        if (Build.VERSION.SDK_INT < 33) {
            PreferencesManager.notificationsAsked = true
            navController.navigate(Screen.Home) {
                popUpTo(Screen.Onboarding) { inclusive = true }
            }
        } else if (ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS)
            == PackageManager.PERMISSION_GRANTED
        ) {
            PreferencesManager.notificationsAsked = true
            navController.navigate(Screen.Home) {
                popUpTo(Screen.Onboarding) { inclusive = true }
            }
        } else if (ActivityCompat.shouldShowRequestPermissionRationale(context as Activity, Manifest.permission.POST_NOTIFICATIONS)) {
            showRationale = true
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(bg),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            modifier = Modifier.padding(32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                "Laplace te avisa",
                style = MaterialTheme.typography.headlineMedium,
                color = text,
                fontWeight = FontWeight.Bold,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(12.dp))
            Text(
                "cuando hay nuevos picks y resultados en vivo",
                style = MaterialTheme.typography.bodyLarge,
                color = textMuted,
                textAlign = TextAlign.Center,
            )

            Spacer(Modifier.height(40.dp))

            Button(
                onClick = { requestPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS) },
                colors = ButtonDefaults.buttonColors(containerColor = accent, contentColor = text),
                modifier = Modifier.fillMaxWidth().height(50.dp),
                shape = RoundedCornerShape(12.dp),
            ) {
                Text("Aceptar", fontWeight = FontWeight.SemiBold)
            }

            Spacer(Modifier.height(12.dp))

            TextButton(onClick = {
                PreferencesManager.notificationsAsked = true
                navController.navigate(Screen.Home) {
                    popUpTo(Screen.Onboarding) { inclusive = true }
                }
            }) {
                Text("Omitir", color = textMuted)
            }
        }
    }
}
