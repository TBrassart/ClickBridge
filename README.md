![Presentation de ClickBridge](https://github.com/TBrassart/ClickBridge/blob/main/images/Presentation.png?raw=true "Presentation")

# ClickBridge

ClickBridge relie un Zwift Click V1 ou un Zwift Ride à Windows et transforme leurs boutons en actions configurables.

La prise en charge du Zwift Ride est expérimentale : elle s’appuie sur des captures du firmware 1.1.0 et n’a pas encore été validée sur un appareil réel avec cette version de ClickBridge. Le Ride comprend deux unités Bluetooth (gauche et droite) ; la compatibilité simultanée des connexions dépend aussi de l’adaptateur Bluetooth du PC.

## Télécharger

**[Télécharger ClickBridge v1.0.6 pour Windows](https://github.com/TBrassart/ClickBridge/releases/latest/download/ClickBridge-Setup.exe)**

La version publiée et son manifeste SHA-256 se trouvent sur la [page des releases](https://github.com/TBrassart/ClickBridge/releases). ClickBridge est actuellement distribué sans certificat de signature éditeur. Windows SmartScreen peut donc afficher un avertissement indiquant que l’éditeur est inconnu. Pour vérifier le fichier, télécharge aussi `SHA256SUMS.txt` depuis la même release et compare l’empreinte :

```powershell
Get-FileHash .\ClickBridge-Setup.exe -Algorithm SHA256
```

L’empreinte affichée doit correspondre à celle indiquée pour `ClickBridge-Setup.exe` dans `SHA256SUMS.txt`. Télécharge l’installateur uniquement depuis les releases officielles de ce dépôt.

## Installer

1. Télécharge `ClickBridge-Setup.exe` depuis le lien ci-dessus.
2. Ouvre le fichier et accepte la demande Windows d’autorisation d’installation.
3. À la fin, laisse cochée l’option de lancement de ClickBridge si tu veux l’ouvrir immédiatement.
4. Active le Bluetooth de Windows et réveille le Zwift Click ou les unités Zwift Ride à proximité.
5. Dans ClickBridge, vérifie l’état des périphériques. Les réglages de profils et de démarrage sont accessibles dans **Configuration**.

Pour mettre à jour, utilise **Configuration → Vérifier les mises à jour**, ou télécharge la dernière version depuis la page des releases. L’installateur met à jour l’application sans supprimer les paramètres utilisateur.

## Problèmes fréquents

### Windows affiche « Windows a protégé votre ordinateur » ou un éditeur inconnu

ClickBridge n’est pas signé par un certificat éditeur, ce qui peut déclencher SmartScreen. Vérifie que le fichier vient bien de la [page officielle des releases](https://github.com/TBrassart/ClickBridge/releases) et compare son empreinte SHA-256 avec le manifeste de cette release avant de poursuivre.

### Le Zwift Click ou le Zwift Ride n’apparaît pas ou ne se connecte pas

Vérifie que le Bluetooth est activé dans Windows et que l’appareil est réveillé et proche du PC, puis relance la recherche depuis ClickBridge. Ferme Zwift et toute autre application susceptible d’être connectée aux mêmes appareils. Pour le Ride, les deux unités gauche et droite se connectent séparément ; si une seule apparaît, vérifie l’adaptateur Bluetooth et exporte un diagnostic après l’avoir vérifié.

### La fenêtre n’est pas visible

ClickBridge peut se trouver dans la zone de notification près de l’horloge. Ouvre son menu contextuel puis choisis **Afficher**.

### L’application ne démarre pas après l’installation

Vérifie que l’installation est terminée, puis lance ClickBridge depuis le menu Démarrer. Si un message d’erreur apparaît, note son texte exact et signale le problème. Utilise la dernière release disponible.

## Signaler un problème

Les signalements se font dans les [GitHub Issues](https://github.com/TBrassart/ClickBridge/issues/new/choose). Ils sont publics : n’y publie pas de mot de passe, adresse personnelle, configuration complète ou autre donnée privée. Le formulaire demande la version de ClickBridge, la version de Windows, les étapes et le résultat observé.

Pour savoir comment exporter et vérifier un diagnostic avant de le joindre, consulte [Aide et diagnostic](SUPPORT.md).

## État du projet

La release actuelle est **v1.0.6**. Elle ajuste la fenêtre principale pour que les contrôles et statistiques restent visibles quand le Zwift Ride est sélectionné. Elle conserve les corrections de mise à jour et l’affichage groupé des deux unités Ride. Pour les problèmes, les demandes et les informations de confidentialité, consulte [Aide et diagnostic](SUPPORT.md).
