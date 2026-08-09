package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"sync"
	"time"
)

type resp struct {
	r *http.Response
	e error
}

func main() {
	var (
		showHelp       bool
		timeoutSeconds int
	)

	flag.IntVar(&timeoutSeconds, "t", 15, "HTTP request timeout in seconds")
	flag.IntVar(&timeoutSeconds, "timeout", 15, "HTTP request timeout in seconds")

	flag.BoolVar(&showHelp, "h", false, "show help")
	flag.BoolVar(&showHelp, "help", false, "show help")

	flag.Parse()

	if showHelp {
		flag.Usage = func() {
			_, _ = fmt.Fprintf(flag.CommandLine.Output(),
				"Usage: %s [options] URL [URL...]\n\nOptions:\n",
				os.Args[0],
			)

			_, _ = fmt.Fprintln(flag.CommandLine.Output(), "  -t, --timeout SECONDS")
			_, _ = fmt.Fprintln(flag.CommandLine.Output(), "        HTTP request timeout (default: 15)")
			_, _ = fmt.Fprintln(flag.CommandLine.Output(), "  -h, --help")
			_, _ = fmt.Fprintln(flag.CommandLine.Output(), "        Show this help")
		}
		flag.Usage()
		return
	}

	if timeoutSeconds <= 0 {
		_, _ = fmt.Fprintln(os.Stderr, "error: timeout must be greater than 0")
		os.Exit(1)
	}

	urls := flag.Args()
	if len(urls) == 0 {
		_, _ = fmt.Fprintln(os.Stderr, "error: at least one URL is required")
		os.Exit(1)
	}

	timeout := time.Duration(timeoutSeconds) * time.Second

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	ch := make(chan resp, len(urls))

	var wg sync.WaitGroup
	wg.Add(len(urls))
	for _, url := range urls {
		go func() {
			defer wg.Done()

			r := request(ctx, url, timeout)
			ch <- r
		}()
	}

	go func() {
		wg.Wait()
		close(ch)
	}()

	var (
		errJoin    error
		allTimeout = true
	)
	for r := range ch {
		if r.e != nil {
			errJoin = errors.Join(errJoin, r.e)
			if !isTimeout(r.e) {
				allTimeout = false
			}
			continue
		}

		if err := printResponse(os.Stdout, r.r); err != nil {
			cancel()
			_, _ = fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		cancel()
		return
	}

	if errJoin != nil {
		_, _ = fmt.Fprintln(os.Stderr, errJoin)
		if allTimeout {
			os.Exit(228)
		}
		os.Exit(1)
	}
}

func printResponse(w io.Writer, response *http.Response) error {
	defer response.Body.Close()

	if _, err := fmt.Fprintf(w, "Status: %s\nHeaders:\n", response.Status); err != nil {
		return err
	}
	if err := response.Header.Write(w); err != nil {
		return err
	}
	if _, err := fmt.Fprintln(w, "Body:"); err != nil {
		return err
	}
	_, err := io.Copy(w, response.Body)
	return err
}

func isTimeout(err error) bool {
	if errors.Is(err, context.DeadlineExceeded) {
		return true
	}

	var netErr net.Error
	return errors.As(err, &netErr) && netErr.Timeout()
}

func request(ctx context.Context, u string, timeout time.Duration) resp {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return resp{e: err}
	}

	client := &http.Client{
		Timeout: timeout,
	}

	response, err := client.Do(req)
	if err != nil {
		return resp{e: err}
	}

	return resp{
		r: response,
		e: nil,
	}
}
