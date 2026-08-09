package main

import (
	"log"
	"os"
)

func main() {
	os.Args = os.Args[1:]

	parseArgs(os.Args)
}

func parseArgs(args []string) {
	for i, arg := range args {
		if i == 0 && (arg == "-h" || arg == "--help") {
			log.Println("Usage: hedgedcurl <command>")
			os.Exit(0)
		}

	}
}
