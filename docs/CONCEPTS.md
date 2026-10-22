# Comprendre ClickBridge

ClickBridge distingue trois notions importantes : le périphérique, le composant et le profil.

Elles remplissent des rôles différents et fonctionnent ensemble pour transformer une commande physique en action clavier.

## 1. Le périphérique : le matériel physique

Un **périphérique** est un équipement physique qui communique avec l'ordinateur.

Exemples :

- Zwift Click V1 ;
- unité gauche du Zwift Ride ;
- unité droite du Zwift Ride.

Le périphérique envoie des événements à ClickBridge, par exemple lorsqu'un bouton est pressé ou relâché.

Dans le cas d'un équipement composé de plusieurs unités Bluetooth, chaque unité peut nécessiter une détection et une connexion distinctes.

## 2. Le composant : la prise en charge logicielle du matériel

Un **composant** est la partie logicielle qui permet à ClickBridge de communiquer avec un type de périphérique et d'interpréter les événements qu'il transmet.

Le composant s'occupe notamment, selon le matériel pris en charge, de :

- rechercher et détecter le périphérique ;
- établir et gérer la connexion ;
- recevoir les événements transmis ;
- interpréter les commandes physiques ;
- transmettre les événements interprétés au reste de ClickBridge.

Chaque matériel peut nécessiter un traitement spécifique. La prise en charge d'un nouveau périphérique demande donc un développement et des tests adaptés.

Un composant n'est pas un profil : il permet à ClickBridge de comprendre le matériel, mais ne détermine pas à lui seul les touches à envoyer à l'application cible.

## 3. Le profil : les actions à exécuter

Un **profil** définit les correspondances entre les événements reconnus par ClickBridge et les actions clavier à effectuer.

Il permet d'adapter le comportement de ClickBridge à une application ou à un usage particulier.

Un profil peut notamment contenir :

- un nom ;
- une association avec une application cible ;
- les touches associées aux différentes commandes disponibles ;
- les paramètres de mapping pris en charge par la version utilisée.

Exemple de principe :

| Événement physique | Action configurée |
|---|---|
| Bouton + | Envoyer la touche configurée pour cette commande |
| Bouton − | Envoyer la touche configurée pour cette commande |
| Direction gauche | Envoyer la flèche gauche, si l'événement et cette action sont pris en charge |

Les correspondances ci-dessus sont illustratives : les événements disponibles dépendent du périphérique, du composant et de la version de ClickBridge.

## 4. Comment les trois éléments fonctionnent ensemble

Le fonctionnement peut être résumé en quatre étapes :

1. **Le périphérique** transmet un événement physique.
2. **Le composant** interprète cet événement.
3. **Le profil** détermine l'action associée à cet événement.
4. **ClickBridge** transmet l'action clavier à Windows.

Le résultat dépend donc du bon fonctionnement de ces trois éléments.

## 5. Pourquoi les distinguer ?

### Changer de profil

Changer de profil permet de modifier les actions associées aux événements déjà pris en charge.

Cela ne permet pas, à lui seul, d'ajouter la prise en charge d'un nouveau matériel ou de nouveaux événements.

### Ajouter un composant

Ajouter un composant permet d'étendre la prise en charge logicielle à un matériel ou à un protocole spécifique.

Cela ne définit pas automatiquement les touches adaptées à chaque application.

### Connecter un périphérique

Connecter un périphérique permet à ClickBridge de recevoir ses événements. Pour obtenir le comportement attendu, il faut également disposer d'un composant compatible et d'un profil adapté.

## À retenir

- **Périphérique** : le matériel physique.
- **Composant** : le code qui prend en charge ce matériel.
- **Profil** : les correspondances entre événements et actions.

Si une commande ne fonctionne pas, cette distinction aide à déterminer si le problème vient de la connexion, de l'interprétation de l'événement ou du mapping configuré.

## Voir aussi

- [Installation et première connexion](INSTALLATION.md)
- [Créer et gérer des profils](PROFILES.md)
- [Dépannage](SUPPORT.md)
