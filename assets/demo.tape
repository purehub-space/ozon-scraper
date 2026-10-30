Output assets/demo.gif

Set FontSize 15
Set FontFamily "Menlo"
Set Width 1180
Set Height 640
Set Padding 18
Set MarginFill "#1e1e2e"
Set Theme "Catppuccin Mocha"
Set TypingSpeed 38ms
Set Shell "bash"

Hide
Type "cd /Users/a1234/Workspace/haiou/ozon-scraper && rm -rf demo && clear"
Enter
Show

Type "echo '# ozon-scraper | image search: one photo -> full catalog matches, 60 SKU/s'"
Enter
Sleep 700ms

Type "python3 ozon_image.py --url 'https://ir-20.ozonstatic.cn/s3/multimedia-1-e/7401951734.jpg' --out demo --pages 1-25 --threads 6"
Enter
Sleep 13s

Type "echo"
Enter
Type "head -3 demo/products.jsonl"
Enter
Sleep 3s

Type "echo"
Enter
Type "wc -l demo/skus.txt"
Enter
Sleep 2s
