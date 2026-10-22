# Installation et première connexion

Ce guide explique comment installer ClickBridge sur Windows, démarrer l'application et vérifier le fonctionnement d'un périphérique compatible.

## 1. Télécharger ClickBridge

Télécharge la dernière version publiée depuis la page officielle :

**[Télécharger ClickBridge](https://github.com/TBrassart/ClickBridge/releases/latest)**

Dans la section des fichiers de la version, télécharge `ClickBridge-Setup.exe`.

Privilégie toujours les versions publiées sur le dépôt officiel. Ne télécharge pas l'installateur depuis un site tiers.

## 2. Installer l'application

1. Ouvre le dossier dans lequel tu as téléchargé l'installateur.
2. Double-clique sur `ClickBridge-Setup.exe`.
3. Si Windows affiche un avertissement de sécurité, consulte la page [Signature de code et SmartScreen](SMARTSCREEN.md) avant de poursuivre.
4. Suis les instructions de l'installateur.
5. Une fois l'installation terminée, démarre ClickBridge.

L'installateur peut être détecté par Windows SmartScreen comme provenant d'un éditeur inconnu, car ClickBridge ne dispose pas actuellement d'un certificat de signature de code reconnu. Cet avertissement ne permet pas, à lui seul, de déterminer si un fichier est malveillant ou non.

## 3. Préparer le périphérique

Avant de lancer la connexion :

- Active le Bluetooth dans les paramètres Windows.
- Allume ou réveille ton périphérique.
- Vérifie que sa batterie est suffisamment chargée.
- Place-le à proximité de l'ordinateur.
- Ferme les applications susceptibles d'utiliser déjà le même périphérique Bluetooth.

Un périphérique déjà connecté à une autre application peut ne pas être disponible pour ClickBridge.

## 4. Première connexion

1. Lance ClickBridge.
2. Vérifie l'état affiché dans l'application.
3. Attends que ton périphérique soit détecté et que la connexion soit établie.
4. Vérifie que le profil adapté à ton application est sélectionné.
5. Teste une commande dans l'application cible.

Si ClickBridge propose un état de connexion ou un indicateur dans la zone de notification Windows, utilise-le pour vérifier que l'application fonctionne comme prévu.

Pour le Zwift Ride, les unités gauche et droite sont des périphériques Bluetooth distincts. Leur détection et leur fonctionnement doivent être vérifiés séparément. La compatibilité dépend de la version de ClickBridge et doit être confirmée par des essais sur le matériel réel.

## 5. Vérifier le fonctionnement

Effectue un premier test avec une action simple et facilement identifiable.

Vérifie les points suivants :

- Le périphérique est détecté.
- La connexion reste active.
- Le profil souhaité est sélectionné.
- La commande physique déclenche l'action clavier attendue.
- Le résultat est correct dans l'application cible.

Si une commande ne fonctionne pas, consulte le [guide de dépannage](SUPPORT.md).

## 6. Retrouver ClickBridge après le démarrage

Si la fenêtre n'est plus visible, vérifie la zone de notification Windows, près de l'horloge. L'application peut y être présente si elle a été réduite dans la barre de notification.

## 7. Mettre à jour ClickBridge

Pour installer une nouvelle version :

1. Consulte les [dernières releases](https://github.com/TBrassart/ClickBridge/releases/latest).
2. Télécharge l'installateur officiel.
3. Ferme ClickBridge si nécessaire.
4. Lance l'installateur et suis les instructions.
5. Redémarre l'application et vérifie que tes profils fonctionnent toujours.

Avant une mise à jour importante, conserve une copie de tes profils exportés si cette fonctionnalité est disponible dans ta version.

## 8. Désinstaller ClickBridge

La désinstallation s'effectue depuis les paramètres Windows, dans la section consacrée aux applications installées.

Si tu souhaites réutiliser tes profils ultérieurement, exporte-les avant la désinstallation et conserve les fichiers dans un emplacement sûr.

## Besoin d'aide ?

- [Comprendre les périphériques, composants et profils](CONCEPTS.md)
- [Gérer les profils](PROFILES.md)
- [Dépannage](TROUBLESHOOTING.md)
- [Signature de code et SmartScreen](SMARTSCREEN.md)
