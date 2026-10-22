# Dépannage ClickBridge

Ce guide présente les problèmes courants pouvant survenir lors de l'utilisation de ClickBridge sous Windows.

Avant toute manipulation, note la version de ClickBridge, le périphérique utilisé et le résultat attendu. Si un message d'erreur apparaît, conserve son texte exact.

## 1. ClickBridge ne détecte pas le périphérique

**Symptôme :** le périphérique n'apparaît pas ou l'application reste en recherche.

**Causes possibles :**
- Bluetooth désactivé ;
- périphérique éteint ou en veille ;
- batterie insuffisamment chargée ;
- périphérique déjà utilisé par une autre application ;
- périphérique non pris en charge par la version utilisée.

**Actions à effectuer :**

1. Vérifie que le Bluetooth est activé dans Windows.
2. Réveille le périphérique et rapproche-le de l'ordinateur.
3. Vérifie son niveau de batterie.
4. Ferme les applications susceptibles d'utiliser le périphérique.
5. Relance la recherche ou redémarre ClickBridge.
6. Si le problème persiste, collecte les informations nécessaires à un signalement.

## 2. Le périphérique est détecté, mais la connexion échoue

**Symptôme :** le matériel apparaît, mais la connexion n'aboutit pas ou ne reste pas active.

**Actions à effectuer :**

1. Vérifie que le périphérique n'est pas déjà connecté à une autre application.
2. Éloigne les sources potentielles d'interférences et rapproche le périphérique du PC.
3. Vérifie que les pilotes Bluetooth de Windows fonctionnent correctement.
4. Désactive puis réactive le Bluetooth si nécessaire.
5. Redémarre ClickBridge et réessaie.

Si l'erreur se reproduit, note si elle survient immédiatement ou après plusieurs secondes.

## 3. Une unité du Zwift Ride est détectée, mais pas l'autre

Le Zwift Ride comprend deux unités Bluetooth distinctes. La détection de l'une ne garantit pas que l'autre soit connectée.

**Actions à effectuer :**

1. Réveille les deux unités.
2. Vérifie leur batterie et leur proximité avec le PC.
3. Ferme les autres applications qui pourraient utiliser l'une des unités.
4. Relance la recherche dans ClickBridge.
5. Note précisément quelle unité est détectée et laquelle ne l'est pas.

La compatibilité et le fonctionnement simultané des deux unités doivent être confirmés avec la version de ClickBridge et le matériel réellement utilisé.

## 4. La connexion se coupe pendant l'utilisation

**Causes possibles :**
- batterie faible ;
- périphérique trop éloigné ;
- perte temporaire de la connexion Bluetooth ;
- mise en veille de Windows ;
- conflit avec une autre application.

**Actions à effectuer :**

- Vérifie la batterie et la distance.
- Ferme les applications concurrentes.
- Note si la déconnexion se produit après une période d'inactivité ou une sortie de veille.
- Relance ClickBridge et vérifie si la reconnexion s'effectue.
- Si le problème est répétitif, prépare un signalement avec les étapes permettant de le reproduire.

## 5. Le bouton fonctionne, mais la mauvaise touche est envoyée

**Symptôme :** une action est détectée, mais le résultat dans l'application n'est pas celui attendu.

**Actions à effectuer :**

1. Vérifie le profil actif.
2. Contrôle la correspondance entre l'événement et la touche configurée.
3. Vérifie que le profil est adapté à l'application cible.
4. Si la sélection automatique est utilisée, vérifie le nom de l'exécutable configuré.
5. Teste la touche dans une application simple qui permet de constater le résultat.

Vérifie particulièrement les touches spéciales comme Entrée, Espace, Échap et les flèches directionnelles.

## 6. Les commandes ne fonctionnent pas dans l'application cible

Si les commandes semblent être reçues par ClickBridge, mais que l'application cible ne réagit pas :

- vérifie que l'application cible est active ;
- vérifie qu'elle accepte les commandes clavier configurées ;
- contrôle le mapping du profil ;
- vérifie qu'une autre fenêtre ne reçoit pas les frappes ;
- teste une autre touche ou une autre action connue comme fonctionnelle.

Le fait qu'un périphérique soit connecté ne garantit pas que chaque touche configurée soit adaptée à l'application cible.

## 7. Les appuis longs ou les répétitions se comportent mal

Si une commande se répète trop rapidement, trop lentement ou ne s'arrête pas comme prévu :

1. Vérifie les paramètres de répétition disponibles.
2. Contrôle le profil actif.
3. Teste un appui court, puis un appui long.
4. Vérifie si le comportement dépend d'un seul bouton ou de toutes les commandes.
5. Note les délais configurés et le résultat observé.

Si le problème concerne une seule action, indique précisément laquelle dans le signalement.

## 8. La fenêtre a disparu

ClickBridge peut être réduit dans la zone de notification Windows, près de l'horloge.

Vérifie si son icône est présente et utilise le menu contextuel pour afficher de nouveau la fenêtre, si cette option est disponible.

## 9. ClickBridge ne démarre pas

**Actions à effectuer :**

1. Vérifie que l'installation s'est terminée correctement.
2. Essaie de lancer ClickBridge depuis le menu Démarrer.
3. Note le message exact affiché par Windows ou par l'application.
4. Vérifie si le problème est apparu après une mise à jour.
5. Télécharge à nouveau l'installateur depuis les [releases officielles](https://github.com/TBrassart/ClickBridge/releases).

Si Windows affiche un avertissement SmartScreen, consulte le [guide consacré à la signature de code](SMARTSCREEN.md).

Ne désactive pas globalement l'antivirus ou les protections Windows pour contourner une erreur.

## 10. La mise à jour ou l'import d'un profil échoue

Pour une mise à jour, vérifie la provenance de l'installateur et recommence avec le fichier de la release officielle.

Pour un import de profil :
- vérifie le fichier sélectionné ;
- conserve le message d'erreur exact ;
- vérifie que le format est compatible ;
- évite de supprimer manuellement les fichiers internes de ClickBridge.

Si le problème persiste, précise la version précédente et la version cible, si elles sont connues.

## 11. Préparer un signalement

Si aucune solution ne fonctionne, rassemble les informations suivantes :

- version de ClickBridge ;
- version de Windows ;
- périphérique utilisé ;
- profil actif ;
- étapes permettant de reproduire le problème ;
- résultat attendu et résultat observé ;
- message d'erreur exact ;
- fréquence du problème.

Si une fonction d'export de diagnostic est disponible dans ta version, suis le [guide de transmission d'un diagnostic](DIAGNOSTICS.md).

## Voir aussi

- [Installation et première connexion](INSTALLATION.md)
- [Gestion des profils](PROFILES.md)
- [Diagnostic et confidentialité](DIAGNOSTICS.md)
- [Signature de code et SmartScreen](SMARTSCREEN.md)
