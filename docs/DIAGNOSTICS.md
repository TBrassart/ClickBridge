# Transmettre un rapport de diagnostic

Lorsque ClickBridge rencontre un problème, un signalement précis permet d'identifier plus rapidement son origine.

Ce guide explique comment préparer un rapport utile et limiter les informations personnelles transmises.

## 1. Avant de commencer

Note les informations suivantes :

- **Version de ClickBridge** : version affichée par l'application ou installée sur ton ordinateur.
- **Système d'exploitation** : version de Windows.
- **Périphérique** : modèle utilisé.
- **Profil actif** : nom du profil sélectionné.
- **Application cible** : application dans laquelle le problème se produit.
- **Moment du problème** : au démarrage, pendant la connexion, lors d'une commande ou après une période d'inactivité.

Ne communique jamais de mot de passe, de clé privée ou de jeton d'accès.

## 2. Reproduire le problème

Si tu peux le faire sans risque :

1. Ferme les applications inutiles susceptibles d'utiliser le même périphérique.
2. Lance ClickBridge.
3. Reproduis le problème une seule fois.
4. Note les étapes exactes suivies.
5. Conserve le message d'erreur affiché, s'il existe.

Évite de modifier plusieurs paramètres avant de documenter le problème : cela rend son origine plus difficile à identifier.

Pour un problème Bluetooth, précise si le périphérique est détecté, si la connexion est établie et à quel moment elle échoue.

Pour un problème de profil, indique l'événement physique déclenché, la touche attendue et le résultat réellement observé.

## 3. Collecter les informations techniques

Utilise les informations accessibles dans ta version de ClickBridge.

Si l'application propose une fonction d'export de diagnostic, utilise-la et conserve l'archive générée.

Si aucune fonction d'export n'est disponible, rassemble manuellement :
- les messages d'erreur affichés ;
- les journaux de l'application, uniquement s'ils sont accessibles par une méthode documentée ;
- les versions du logiciel et de Windows ;
- les étapes de reproduction ;
- les éventuels changements récents de configuration.

Ne recherche pas au hasard des fichiers internes et ne modifie pas directement les fichiers de configuration pour produire un rapport.

## 4. Vérifier les informations avant de partager le rapport

Avant toute transmission :

- relis le contenu du rapport ;
- retire les noms d'utilisateur et chemins personnels s'ils ne sont pas nécessaires ;
- masque les identifiants Bluetooth si leur divulgation n'est pas nécessaire ;
- ne joins pas tes profils complets sans raison ;
- retire toute donnée personnelle ou information confidentielle ;
- vérifie que l'archive ne contient pas de mot de passe, de jeton ou de secret.

Un journal technique peut contenir davantage d'informations que le simple message d'erreur affiché à l'écran. Ne considère pas une archive comme anonymisée sans en avoir vérifié le contenu.

## 5. Transmettre le rapport

Tu peux signaler un problème sur le dépôt officiel :

**[Ouvrir les issues ClickBridge](https://github.com/TBrassart/ClickBridge/issues/new/choose)**

Avant de créer un ticket, vérifie si un ticket existant décrit déjà le même problème.

Dans le signalement, indique :
1. Un titre court et précis.
2. La version de ClickBridge et de Windows.
3. Le périphérique et le profil concernés.
4. Les étapes exactes pour reproduire le problème.
5. Le résultat attendu.
6. Le résultat observé.
7. Le message d'erreur éventuel.
8. Le rapport de diagnostic, après vérification de son contenu.

Les tickets GitHub d'un dépôt public peuvent être visibles par tous. Ne joins pas d'informations confidentielles.

## 6. Modèle de signalement

Tu peux utiliser le modèle suivant pour structurer ton rapport.

### Description du problème

Décris brièvement ce qui ne fonctionne pas.

### Environnement

- Version de ClickBridge :
- Version de Windows :
- Périphérique :
- Profil actif :
- Application cible :

### Étapes pour reproduire le problème

1.
2.
3.

### Résultat attendu

Décris le comportement attendu.

### Résultat observé

Décris ce qui se produit réellement.

### Fréquence

- [ ] À chaque tentative
- [ ] De façon intermittente
- [ ] Une seule fois jusqu'à présent

### Message d'erreur

Copie le message exact, s'il existe.

### Pièces jointes

Indique si un rapport de diagnostic a été joint et confirme que son contenu a été vérifié.

## 7. Confidentialité

Ne transmets que les informations nécessaires à l'analyse.

Si le rapport contient des données que tu ne souhaites pas publier, ne le joins pas au ticket public. Retire les données concernées ou demande une méthode de transmission adaptée.

La collecte et l'export automatiques d'un diagnostic ne doivent pas être confondus avec son envoi : aucun rapport ne doit être considéré comme transmis tant que tu ne l'as pas partagé explicitement.

## Voir aussi

- [Dépannage](TROUBLESHOOTING.md)
- [Installation](INSTALLATION.md)
- [Signature de code et SmartScreen](SMARTSCREEN.md)
