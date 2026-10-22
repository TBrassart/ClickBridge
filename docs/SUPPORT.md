# Aide et diagnostic

## Exporter un diagnostic

1. Ouvre **Configuration** dans ClickBridge.
2. Dans **Diagnostic avancé**, clique sur **Exporter le diagnostic…**.
3. Garde cochée l’option **Anonymiser les adresses Bluetooth, chemins Windows et noms de profils**.
4. Laisse décochée **Inclure la configuration et les profils**, sauf si le support te le demande et que tu as vérifié le contenu.
5. Laisse décochée l’option de trames brutes. Elle est désactivée tant que la capture avancée n’a pas été activée pendant cette session.
6. Choisis où enregistrer l’archive `ClickBridge-Diagnostic-AAAA-MM-JJ.zip`.

ClickBridge ne transmet pas cette archive automatiquement. Elle reste sur ton ordinateur jusqu’à ce que tu la joignes toi-même à un signalement.

## Contenu et confidentialité

L’archive contient normalement :

- `diagnostic.json` : versions de ClickBridge et de Windows, état Bluetooth, profils actif et par défaut, et options de diagnostic ;
- `application.log` et `errors.log` : les journaux récents et les avertissements ou erreurs ;
- `device-info.json` et `compatibility.json` : informations du périphérique et compatibilité.

Pour le Zwift Ride, l’archive décrit séparément les unités gauche et droite. La prise en charge actuelle est expérimentale et basée sur l’analyse du firmware 1.1.0 ; un diagnostic peut aider à distinguer un problème de découverte d’un problème de connexion ou de protocole.

La configuration complète n’est pas ajoutée par défaut. Avec l’anonymisation activée, ClickBridge masque notamment les adresses Bluetooth, l’identifiant du périphérique, les noms des profils et les noms d’utilisateur dans les chemins Windows. Cette anonymisation ne garantit pas la détection de toute donnée personnelle pouvant apparaître dans un texte de journal.

Les trames Bluetooth brutes peuvent révéler des détails techniques propres à ton appareil. La capture du protocole est désactivée par défaut et limitée à la session ; l’archive ne les inclut que si tu as activé cette capture et choisi de les inclure à l’export.

**Avant de joindre l’archive à un ticket public, ouvre-la et vérifie les fichiers qu’elle contient.** Retire toute information personnelle. N’inclus pas ta configuration, tes profils ou des trames brutes si ce n’est pas nécessaire.

## Où demander de l’aide

Crée un ticket dans les [GitHub Issues de ClickBridge](https://github.com/TBrassart/ClickBridge/issues/new/choose). Les tickets sont publics. Indique :

- la version de ClickBridge (`Configuration` ou le titre de l’application) ;
- la version de Windows ;
- l’appareil et son état (éteint, allumé, connecté, batterie si connue) ;
- les étapes exactes pour reproduire le problème ;
- le résultat attendu et le résultat observé ;
- le message d’erreur exact, s’il y en a un.

Joindre un diagnostic est facultatif. Si tu le joins, vérifie d’abord son contenu et n’ajoute jamais de mots de passe, jetons, adresse personnelle ou fichier de configuration complet.

## Installation et SmartScreen

L’installateur actuel n’est pas signé par un certificat éditeur. SmartScreen peut afficher un avertissement d’éditeur inconnu. Télécharge toujours le programme depuis les [releases officielles](https://github.com/TBrassart/ClickBridge/releases) et compare éventuellement le SHA-256 de l’installateur au fichier `SHA256SUMS.txt` fourni avec cette release.

## Dépannage rapide

### Un seul côté du Zwift Ride est connecté

Les unités gauche et droite sont deux périphériques Bluetooth distincts. Réveille les deux, rapproche-les du PC et ferme Zwift ainsi que toute autre application qui pourrait les utiliser. Laisse ClickBridge rechercher les deux unités ; si un côté reste absent, désactive puis réactive le Bluetooth Windows et relance ClickBridge. La compatibilité de deux connexions simultanées dépend de l’adaptateur Bluetooth. Le Ride est encore expérimental.

### ClickBridge indique une recherche ou perd la connexion

Vérifie que le Bluetooth Windows est activé, que l’appareil est réveillé et suffisamment chargé, puis laisse quelques instants à la recherche pour reprendre. Après une sortie de veille, réactive le Bluetooth si nécessaire. Ferme les applications qui peuvent monopoliser l’appareil. Si l’appareil n’est pas reconnu même après un redémarrage de ClickBridge, il peut être incompatible avec les pilotes pris en charge actuellement.

### L’application se ferme ou affiche une erreur Bluetooth

Note le message exact et le moment où il apparaît : lancement, recherche, connexion, veille/reprise ou commande. ClickBridge devrait rester ouvert lorsqu’un appareil est éteint ou indisponible. Exporte un diagnostic anonymisé et signale tout plantage reproductible avec les étapes qui l’ont déclenché.

### Le niveau de batterie est absent ou faible

Certaines versions ou certains états de l’appareil ne transmettent pas immédiatement le niveau de batterie. Réveille l’appareil et laisse la connexion s’établir. Si le niveau reste absent, joins un diagnostic. Recharge l’appareil si le pourcentage est bas ; une coupure sous charge peut aussi venir d’une batterie faible.

### La fenêtre paraît coupée ou les commandes ne sont pas visibles

Utilise une version récente depuis les releases officielles. Depuis **v1.0.6**, l’écran Ride est plus compact ; **v1.0.7.1** affine le style des cartes, des commandes et du logo. Vérifie que la fenêtre n’est pas simplement masquée dans la zone de notification. Si le bas reste coupé, indique la résolution de l’écran, le facteur de mise à l’échelle Windows et le périphérique sélectionné.

### La mise à jour affiche « Failed to load Python DLL » ou ne relance pas l’application

Ferme ClickBridge puis installe la dernière version depuis la [page officielle des releases](https://github.com/TBrassart/ClickBridge/releases). Les versions récentes corrigent le mécanisme de mise à jour qui pouvait échouer lors du remplacement ou du redémarrage de l’application. Les paramètres utilisateur sont conservés par l’installateur.

### Les profils ou réglages semblent incorrects

Ne supprime pas le fichier de configuration manuellement. Utilise **Configuration → Restaurer sauvegarde…** pour revenir à une sauvegarde, ou **Restaurer les paramètres par défaut…** pour réinitialiser après création d’une sauvegarde. Pour un problème persistant, exporte un diagnostic anonymisé avant de contacter le support.

## Validation d’une version

Une [checklist de validation](VALIDATION.md) aide à vérifier l’installation, l’interface, les commandes, la reconnexion, les profils et le diagnostic. Les contrôles Zwift Ride nécessitent les deux unités physiques ; note-les comme non testés si tu ne les as pas sous la main.
