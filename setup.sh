#!/bin/bash

# Create essential files
touch .env.example
touch .gitignore
touch CHANGELOG.md
touch LICENSE

# Verify the structure was created
tree -a  # or use 'find . -type d' if tree is not installed