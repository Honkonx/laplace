package com.laplace.mobile.navigation

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CalendarMonth
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.TrendingUp
import androidx.compose.material.icons.filled.Psychology
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import androidx.navigation.compose.currentBackStackEntryAsState
import com.laplace.mobile.ui.theme.accent
import com.laplace.mobile.ui.theme.surface
import com.laplace.mobile.ui.theme.textMuted

private data class TabItem(
    val label: String,
    val icon: ImageVector,
    val screen: Screen,
)

private val tabs = listOf(
    TabItem("Inicio", Icons.Filled.Home, Screen.Home),
    TabItem("Calendario", Icons.Filled.CalendarMonth, Screen.Calendar),
    TabItem("Picks", Icons.Filled.Star, Screen.TopPicks),
    TabItem("Stats", Icons.Filled.TrendingUp, Screen.Stats),
    TabItem("Perfil", Icons.Filled.Person, Screen.Profile),
    TabItem("Laplace", Icons.Filled.Psychology, Screen.Agent),
)

@Composable
fun BottomNavBar(navController: NavController) {
    val navBackStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = navBackStackEntry?.destination?.route

    NavigationBar(
        containerColor = surface,
    ) {
        tabs.forEach { tab ->
            val selected = currentRoute == tab.screen::class.qualifiedName
            NavigationBarItem(
                selected = selected,
                onClick = {
                    if (!selected) {
                        navController.navigate(tab.screen) {
                            popUpTo(Screen.Home::class.qualifiedName ?: "") { saveState = true }
                            launchSingleTop = true
                            restoreState = true
                        }
                    }
                },
                icon = { Icon(tab.icon, contentDescription = tab.label) },
                label = { Text(tab.label) },
                colors = NavigationBarItemDefaults.colors(
                    selectedIconColor = accent,
                    selectedTextColor = accent,
                    unselectedIconColor = textMuted,
                    unselectedTextColor = textMuted,
                    indicatorColor = accent.copy(alpha = 0.1f),
                ),
            )
        }
    }
}
