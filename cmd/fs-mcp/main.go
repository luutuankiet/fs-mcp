package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"os"
	"syscall"
	"time"

	"github.com/luutuankiet/fs-mcp/internal/bootstrap"
	"github.com/luutuankiet/fs-mcp/internal/portal"
	"github.com/luutuankiet/fs-mcp/internal/server"
	"github.com/luutuankiet/fs-mcp/internal/updater"
)

var version = "dev"

func main() {
	httpAddr := flag.String("http", "", "HTTP streamable address (e.g. :8124). Empty = stdio.")
	showVersion := flag.Bool("version", false, "Print version and exit.")
	showRoot := flag.Bool("print-root", false, "Print detected portal root and exit.")
	doctor := flag.Bool("doctor", false, "Check and install managed dependencies (jq, yq, rg, rtk), then exit.")
	skipBootstrap := flag.Bool("skip-bootstrap", false, "Skip the managed-dep check on startup (expert use).")
	skipUpdate := flag.Bool("skip-update", false, "Skip the self-update check on startup (expert use).")
	flag.Parse()

	if *showVersion {
		fmt.Println("fs-mcp", version)
		return
	}

	if *doctor {
		runDoctor()
		return
	}

	if !*skipUpdate && os.Getenv("FS_MCP_NO_AUTO_UPDATE") != "1" {
		maybeSelfUpdate()
	}

	if !*skipBootstrap {
		if err := ensureDeps(); err != nil {
			log.Fatalf("bootstrap: %v", err)
		}
	}

	cliRoot := ""
	if flag.NArg() > 0 {
		cliRoot = flag.Arg(0)
	}
	d, err := portal.Detect(cliRoot)
	if err != nil {
		log.Fatalf("portal detect: %v", err)
	}
	log.Printf("portal root=%s (source=%s)", d.Root, d.Source)

	if *showRoot {
		fmt.Println(d.Root)
		return
	}

	if err := os.Chdir(d.Root); err != nil {
		log.Printf("warning: chdir %s failed: %v", d.Root, err)
	}

	opts := server.Options{
		Name:     "fs-mcp",
		Version:  version,
		Root:     d.Root,
		HTTPAddr: *httpAddr,
	}
	if err := server.Run(context.Background(), opts); err != nil {
		log.Fatalf("server: %v", err)
	}
}

func ensureDeps() error {
	statuses, err := bootstrap.Ensure()
	if err != nil {
		return err
	}
	bin, err := bootstrap.BinDir()
	if err == nil {
		bootstrap.WirePath(bin)
	}
	for _, st := range statuses {
		if st.Error != nil {
			for _, d := range bootstrap.Manifest() {
				if d.Name == st.Name && d.Required {
					return fmt.Errorf("required dep %s: %v", st.Name, st.Error)
				}
			}
			log.Printf("bootstrap: optional dep %s unavailable: %v", st.Name, st.Error)
			continue
		}
		tag := "[" + st.Source + "]"
		if st.Installed {
			tag += " installed"
		}
		log.Printf("bootstrap: %s %s %s (%s)", st.Name, st.Version, tag, st.Path)
	}
	return nil
}

// maybeSelfUpdate checks GitHub Releases on cold start. If a newer tag exists,
// it downloads + atomic-renames the binary in place and re-execs. Any failure
// is logged and ignored so a broken network never blocks startup. Skipped for
// dev builds (version=="dev"), when --skip-update is passed, or when the
// FS_MCP_NO_AUTO_UPDATE=1 env var is set.
func maybeSelfUpdate() {
	exePath, err := os.Executable()
	if err != nil {
		log.Printf("auto-update: locate executable: %v", err)
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 35*time.Second)
	defer cancel()
	res, _ := updater.CheckAndUpdate(ctx, version, exePath)
	if res.Updated {
		log.Printf("auto-update: %s → %s, re-execing", res.FromVersion, res.ToVersion)
		argv := append([]string{exePath}, os.Args[1:]...)
		if err := syscall.Exec(exePath, argv, os.Environ()); err != nil {
			log.Printf("auto-update: re-exec failed (%v) — continuing with the just-replaced binary", err)
		}
		return
	}
	if res.Skipped != "" {
		log.Printf("auto-update: %s", res.Skipped)
	}
}

func runDoctor() {
	statuses, err := bootstrap.Ensure()
	if err != nil {
		fmt.Fprintf(os.Stderr, "doctor: %v\n", err)
		os.Exit(1)
	}
	fmt.Println("fs-mcp doctor — managed dependency check")
	fmt.Println()
	fmt.Printf("%-8s %-10s %-10s %s\n", "DEP", "VERSION", "SOURCE", "PATH")
	exitCode := 0
	for _, st := range statuses {
		src := st.Source
		if st.Error != nil {
			src = "ERROR: " + st.Error.Error()
			for _, d := range bootstrap.Manifest() {
				if d.Name == st.Name && d.Required {
					exitCode = 1
				}
			}
		}
		if st.Installed {
			src += " (installed)"
		}
		fmt.Printf("%-8s %-10s %-10s %s\n", st.Name, st.Version, src, st.Path)
	}
	os.Exit(exitCode)
}
