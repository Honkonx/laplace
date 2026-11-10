package com.laplace.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.laplace.mobile.data.local.AuthManager
import com.laplace.mobile.data.local.PreferencesManager
import com.laplace.mobile.data.repository.LogoRepository
import com.laplace.mobile.ui.theme.LaplaceTheme
import com.laplace.mobile.navigation.AppNavHost

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        PreferencesManager.init(this)
        AuthManager.init(this)
        LogoRepository.init(this)
        enableEdgeToEdge()
        setContent {
            LaplaceTheme {
                AppNavHost()
            }
        }
    }
}
