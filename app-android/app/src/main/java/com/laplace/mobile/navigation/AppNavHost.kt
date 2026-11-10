package com.laplace.mobile.navigation

import androidx.compose.foundation.layout.padding
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.Scaffold
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.toRoute
import com.laplace.mobile.data.local.PreferencesManager
import com.laplace.mobile.ui.screens.home.HomeScreen
import com.laplace.mobile.ui.screens.calendar.CalendarScreen
import com.laplace.mobile.ui.screens.toppicks.TopPicksScreen
import com.laplace.mobile.ui.screens.stats.StatsScreen
import com.laplace.mobile.ui.screens.profile.ProfileScreen
import com.laplace.mobile.ui.screens.leagues.LeaguesScreen
import com.laplace.mobile.ui.screens.matches.MatchesScreen
import com.laplace.mobile.ui.screens.prediction.PredictionScreen
import com.laplace.mobile.ui.screens.history.HistoryScreen
import com.laplace.mobile.ui.screens.codigo.CodigoActivacionScreen
import com.laplace.mobile.ui.screens.upgrade.UpgradeScreen
import com.laplace.mobile.ui.screens.config.ConfigThemeScreen
import com.laplace.mobile.ui.screens.log.LogScreen
import com.laplace.mobile.ui.screens.about.AboutScreen
import com.laplace.mobile.ui.screens.onboarding.OnboardingScreen
import com.laplace.mobile.ui.screens.registro.RegistroScreen
import com.laplace.mobile.ui.screens.notifications.NotificationPermissionScreen
import com.laplace.mobile.ui.screens.sports.SportsMenuScreen
import com.laplace.mobile.ui.screens.agent.AgentScreen

@Composable
fun AppNavHost() {
    val navController = rememberNavController()
    val drawerState = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()

    val startDestination = if (PreferencesManager.onboardingDone) Screen.Home else Screen.Onboarding

    ModalNavigationDrawer(
        drawerState = drawerState,
        drawerContent = { DrawerContent(navController) },
    ) {
        Scaffold(
            bottomBar = { BottomNavBar(navController) }
        ) { padding ->
            NavHost(
                navController = navController,
                startDestination = startDestination,
                modifier = Modifier.padding(padding),
            ) {
                composable<Screen.Home> { HomeScreen(navController) }
                composable<Screen.Calendar> { CalendarScreen(navController) }
                composable<Screen.TopPicks> { TopPicksScreen(navController) }
                composable<Screen.Stats> { StatsScreen(navController) }
                composable<Screen.Profile> { ProfileScreen(navController) }
                composable<Screen.Agent> { AgentScreen() }
                composable<Screen.Leagues> { LeaguesScreen(navController, it.toRoute<Screen.Leagues>()) }
                composable<Screen.Matches> { MatchesScreen(navController, it.toRoute<Screen.Matches>()) }
                composable<Screen.Prediction> { PredictionScreen(navController, it.toRoute<Screen.Prediction>()) }
                composable<Screen.History> { HistoryScreen(navController) }
                composable<Screen.CodigoActivacion> { CodigoActivacionScreen(navController) }
                composable<Screen.Upgrade> { UpgradeScreen(navController) }
                composable<Screen.ConfigTheme> { ConfigThemeScreen(navController) }
                composable<Screen.Log> { LogScreen(navController) }
                composable<Screen.About> { AboutScreen(navController) }
                composable<Screen.Onboarding> { OnboardingScreen(navController) }
                composable<Screen.Registro> { RegistroScreen(navController) }
                composable<Screen.NotificationPermission> { NotificationPermissionScreen(navController) }
                composable<Screen.SportsMenu> { SportsMenuScreen(navController) }
            }
        }
    }
}
