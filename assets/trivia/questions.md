<!--
  Generic tech trivia bank that ships with Sonnia. Replace it or add questions about
  your own event, venue or product. Keep every answer unambiguous and verifiable:
  Sonia states the correct option as a fact in front of the audience.
-->

# Trivia questions

Question bank for the trivia mode. In each game Sonia draws 5 questions at random and shuffles their options.
You can edit it without touching code: the orchestrator re-reads this file at the start of every game.

Format of each question:

- One `## ` line with the question, starting with its level in square brackets: `## [easy] ...?`, `[medium]` or `[hard]` (without a level, a question counts as medium). Each level needs at least as many questions as a game has (5): if one falls short, the game is filled with questions from the closest level.
- Three options as a list: `- [x]` marks the correct one and `- [ ]` the other two. Exactly one correct option.
- Optional: one `> ` line with a short fact that Sonia can add when she reveals the answer.

The options are shown on the vertical screen and Sonia reads them aloud: keep them short, under about 35 characters.
A malformed question is skipped with a warning in the log.

## [easy] What does "WWW" stand for?
- [x] World Wide Web
- [ ] Wide World Web
- [ ] Web World Wide
> Tim Berners-Lee invented the web while working at CERN.

## [easy] What does "CPU" stand for?
- [ ] Computer Personal Unit
- [x] Central Processing Unit
- [ ] Central Program Utility
> It's the part of a computer that runs a program's instructions.

## [easy] Which of these is a programming language?
- [ ] HTTP
- [ ] JPEG
- [x] Python
> Python is named after the comedy group Monty Python, not the snake.

## [easy] Which number system do computers use internally?
- [x] Binary
- [ ] Decimal
- [ ] Roman numerals
> Binary uses only two digits: 0 and 1.

## [easy] In programming, what is a "bug"?
- [ ] A brand new feature
- [x] An error in the code
- [ ] A very fast computer
> Engineers once found a real moth stuck inside a computer and taped it into the logbook.

## [easy] Which of these is an operating system?
- [ ] Python
- [ ] Wi-Fi
- [x] Linux
> Android phones run on the Linux kernel.

## [easy] What does "RAM" stand for?
- [x] Random Access Memory
- [ ] Read And Modify
- [ ] Rapid Action Memory
> Most RAM loses its contents when the power goes off.

## [easy] Which language gives a web page its structure?
- [ ] CSS
- [x] HTML
- [ ] SQL
> CSS gives the page its style and JavaScript makes it interactive.

## [easy] What is open-source software?
- [ ] Software with no bugs
- [ ] Apps that only work online
- [x] Code anyone can see and change
> Licenses like MIT let anyone use, change and share the code.

## [easy] On most Windows PCs, which shortcut copies?
- [x] Ctrl + C
- [ ] Ctrl + V
- [ ] Ctrl + Z
> Ctrl + V pastes, and on a Mac you use Command instead of Ctrl.

## [easy] How many bits are there in a byte?
- [ ] 4
- [x] 8
- [ ] 16
> One byte can hold 256 different values.

## [easy] What does Wi-Fi let devices do?
- [ ] Charge without cables
- [ ] Print in 3D
- [x] Connect without cables
> Wi-Fi sends data using radio waves.

## [easy] Which of these makes a password stronger?
- [x] Making it long and unique
- [ ] Using your birthday
- [ ] Using it on every site
> A long phrase of random words is easy to remember and hard to guess.

## [easy] Who is often called the first computer programmer?
- [ ] Alan Turing
- [x] Ada Lovelace
- [ ] Grace Hopper
> In the 1840s she wrote an algorithm for Charles Babbage's Analytical Engine.

## [easy] In an email address, what does the @ separate?
- [ ] The name and the password
- [ ] The date and the time
- [x] The user and the domain
> Ray Tomlinson picked the @ sign for the first network email, in 1971.

## [medium] What does "HTTP" stand for?
- [x] HyperText Transfer Protocol
- [ ] High Tech Transfer Program
- [ ] HyperText Tracking Process
> The S in HTTPS stands for Secure: the connection is encrypted.

## [medium] What does "SQL" stand for?
- [ ] Simple Question Language
- [x] Structured Query Language
- [ ] System Quality Logic
> It's used to read and change data in relational databases.

## [medium] Which data structure is "last in, first out"?
- [ ] A queue
- [ ] A hash table
- [x] A stack
> A queue is the opposite: first in, first out.

## [medium] What does DNS do?
- [x] Turns names into IP addresses
- [ ] Encrypts your passwords
- [ ] Speeds up your Wi-Fi
> It's often called the phone book of the internet.

## [medium] Who created the Linux kernel?
- [ ] Richard Stallman
- [x] Linus Torvalds
- [ ] Bill Gates
> He announced it in 1991 as "just a hobby".

## [medium] Which language did Brendan Eich create in 1995?
- [ ] Java
- [ ] PHP
- [x] JavaScript
> Despite the name, it is a very different language from Java.

## [medium] What does "GPU" stand for?
- [x] Graphics Processing Unit
- [ ] General Purpose Utility
- [ ] Graphic Power Unit
> GPUs are built to do many calculations in parallel.

## [medium] Who proposed the "imitation game" to test if a machine can think?
- [ ] Ada Lovelace
- [x] Alan Turing
- [ ] Charles Babbage
> Today we call it the Turing test.

## [medium] What is Git used for?
- [ ] Compiling programs
- [ ] Hosting websites
- [x] Tracking changes in code
> Linus Torvalds created it in 2005 to manage the Linux code.

## [medium] What is "phishing"?
- [x] Tricking you into giving data
- [ ] A kind of fiber internet
- [ ] A way to speed up a PC
> Check the sender and the link before you type a password.

## [medium] Which sorting algorithm keeps swapping neighboring items?
- [ ] Merge sort
- [x] Bubble sort
- [ ] Quicksort
> It's simple to understand, but slow on long lists.

## [medium] What does "API" stand for?
- [ ] Automated Program Integration
- [ ] Advanced Protocol Internet
- [x] Application Programming Interface
> An API is how one program asks another one for something.

## [medium] What does "IP" stand for in "IP address"?
- [x] Internet Protocol
- [ ] Internal Port
- [ ] Information Provider
> Every device on a network needs an address to send and receive data.

## [medium] In which decade did the World Wide Web go public?
- [ ] The 1970s
- [x] The 1990s
- [ ] The 2000s
> The very first website explained how the web itself worked.

## [medium] Which of these keeps its data when the power is off?
- [ ] RAM
- [ ] The CPU cache
- [x] An SSD
> SSDs store data in flash memory, with no moving parts.

## [hard] Which port does HTTPS use by default?
- [x] 443
- [ ] 80
- [ ] 22
> Plain HTTP uses port 80.

## [hard] Who wrote A-0, one of the very first compilers?
- [ ] Margaret Hamilton
- [x] Grace Hopper
- [ ] John von Neumann
> She also helped shape COBOL, a language still used by many banks.

## [hard] Which language did Dennis Ritchie create at Bell Labs?
- [ ] Pascal
- [ ] Fortran
- [x] C
> He and Ken Thompson used it to rewrite Unix.

## [hard] What does Big O notation describe?
- [x] How an algorithm scales
- [ ] How big a file is
- [ ] How much memory a PC has
> Checking every item in a list once, for example, is O(n).

## [hard] What must be true of a list to use binary search?
- [ ] It must be short
- [x] It must be sorted
- [ ] It must hold only numbers
> Each step halves the part of the list left to search.

## [hard] In databases, what does "ACID" refer to?
- [ ] A query language
- [ ] An encryption method
- [x] Guarantees for transactions
> Atomicity, Consistency, Isolation and Durability.

## [hard] Which OSI layer routes data between networks?
- [x] The network layer
- [ ] The transport layer
- [ ] The physical layer
> It's layer 3, where the IP protocol lives.

## [hard] Which algorithm finds shortest paths in a weighted graph?
- [ ] Kruskal's algorithm
- [x] Dijkstra's algorithm
- [ ] Quicksort
> Edsger Dijkstra said he designed it in about twenty minutes, at a café.

## [hard] What is hexadecimal FF in decimal?
- [ ] 100
- [ ] 256
- [x] 255
> Web colors use two hex digits per channel, from 00 to FF.

## [hard] Which encryption algorithm is named after its three inventors?
- [x] RSA
- [ ] AES
- [ ] SHA-256
> The letters stand for Rivest, Shamir and Adleman.

## [hard] Which data structure offers average constant-time lookups by key?
- [ ] A linked list
- [x] A hash table
- [ ] A binary heap
> Python dictionaries are hash tables.

## [hard] What does TCP guarantee that UDP does not?
- [ ] Encryption of the data
- [ ] Lower latency
- [x] Ordered, reliable delivery
> UDP is lighter, so it's popular for live video and online games.

## [hard] Which version of IP uses 128-bit addresses?
- [x] IPv6
- [ ] IPv4
- [ ] IPv5
> IPv4 uses 32 bits: only about 4.3 billion addresses.

## [hard] Which 1950s language is still big in scientific computing?
- [ ] COBOL
- [x] Fortran
- [ ] Pascal
> Its name comes from FORmula TRANslation.

## [hard] In a regular expression, what does ^ usually match?
- [ ] The end of the text
- [ ] Any single character
- [x] The start of the text
> The dollar sign matches the end of the text.
