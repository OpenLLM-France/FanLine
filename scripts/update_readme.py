#!/usr/bin/env python3
import subprocess
import os
import re
import click

def clean_old_diagrams(output_file: str):
    """Supprime l'ancien fichier PNG s'il existe."""
    try:
        if os.path.exists(output_file):
            os.remove(output_file)
            print(f"🗑️  Ancien fichier supprimé : {output_file}")
    except Exception as e:
        print(f"⚠️  Impossible de supprimer {output_file}: {str(e)}")

def generate_mermaid_diagrams():
    """Génère les diagrammes Mermaid."""
    diagrams = [
        ('queue-architecture.md', 'queue-architecture.png'),
        ('architecture.md', 'architecture.png')
    ]
    
    success = True
    for source, output in diagrams:
        if os.path.exists(source):
            try:
                # Supprime l'ancien fichier avant la génération
                clean_old_diagrams(output)
                
                subprocess.run([
                    'npx', 
                    '@mermaid-js/mermaid-cli',
                    '-i', source,
                    '-o', output,

                    '-s', '2', 
                    '-q', '1.0', 
                    '-w', '1024', 
                    '-H', '1024'
                ], check=True)
                print(f"✅ Diagramme généré : {output}")
            except subprocess.CalledProcessError as e:
                print(f"❌ Erreur lors de la génération de {output}: {str(e)}")
                success = False
        else:
            print(f"⚠️ Fichier source non trouvé : {source}")
            success = False
    return success

def update_readme_schemas():
    """Met à jour les schémas dans le README."""
    try:
        with open('README.md', 'r') as f:
            content = f.read()

        updated = False
        # Mise à jour du schéma de la file d'attente
        queue_pattern = r'(<summary><h3>📊 Schémas de la file d\'attente</h3></summary>\s*<div[^>]*>\s*\n\n)(#Empty|\!\[.*?\].*?\n*)(\s*\n*</div>)'
        if os.path.exists('queue-architecture-1.png'):
            content = re.sub(
                queue_pattern,
                r'\1![Queue Architecture](queue-architecture-1.png)\n\3',
                content,
                flags=re.DOTALL
            )
            updated = True

        # Mise à jour du schéma de l'architecture
        arch_pattern = r'(<summary><h3>🏗️ Schémas de l\'Architecture</h3></summary>\s*<div[^>]*>\s*\n\n)(#Empty|\!\[.*?\].*?\n*)(\s*\n*</div>)'
        if os.path.exists('architecture-1.png'):
            content = re.sub(
                arch_pattern,
                r'\1![Architecture](architecture-1.png)\n\3',
                content,
                flags=re.DOTALL
            )
            updated = True

        if not updated:
            print("⚠️ Aucun schéma PNG trouvé à mettre à jour")
            return False

        with open('README.md', 'w') as f:
            f.write(content)
        print("✅ Schémas du README mis à jour avec succès")
        return True

    except Exception as e:
        print(f"❌ Erreur lors de la mise à jour des schémas: {str(e)}")
        return False

@click.group()
def cli():
    """CLI pour gérer la documentation du projet."""
    pass

@cli.command()
def schemas():
    """Génère les schémas et met à jour le README."""
    print("🔄 Génération des schémas...")
    if generate_mermaid_diagrams():
        print("\n🔄 Mise à jour du README avec les schémas...")
        return
    print("❌ Erreur lors de la mise à jour des schémas")

@cli.command()
def update():
    """Met à jour le README avec les schémas existants sans les régénérer."""
    print("🔄 Mise à jour du README avec les schémas existants...")
    if update_readme_schemas():
        print("✅ Mise à jour terminée")
    else:
        print("❌ Erreur lors de la mise à jour")

@cli.command()
def version():
    """Met à jour la version dans le README."""
    # TODO: Implémenter la mise à jour de la version
    print("🔄 Mise à jour de la version...")
    print("⚠️ Fonctionnalité non implémentée")

@cli.command()
def all():
    """Met à jour tous les éléments du README."""
    print("🔄 Mise à jour complète du README...")
    success = True
    
    # Mise à jour des schémas
    print("\n📊 Mise à jour des schémas...")
    if not generate_mermaid_diagrams() or not update_readme_schemas():
        success = False
    
    # Mise à jour de la version (à implémenter)
    print("\n📝 Mise à jour de la version...")
    print("⚠️ Fonctionnalité non implémentée")
    
    if success:
        print("\n✅ Mise à jour complète terminée avec succès")
    else:
        print("\n⚠️ Certaines mises à jour ont échoué")

if __name__ == "__main__":
    cli() 