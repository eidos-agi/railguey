package main

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"io"
	"os"
	"path/filepath"
	"testing"
)

func TestTokenPrefersWorkspaceFile(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, ".env.local"), []byte("RAILWAY_TOKEN=project-token\n"), 0600); err != nil {
		t.Fatal(err)
	}
	got, err := tokenFor(dir)
	if err != nil || got != "project-token" {
		t.Fatalf("tokenFor() = %q, %v", got, err)
	}
}

func TestTarballExcludesSecretsAndGit(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "app.txt"), []byte("ok"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, ".env.local"), []byte("RAILWAY_TOKEN=secret"), 0600); err != nil {
		t.Fatal(err)
	}
	archive, err := tarball(dir)
	if err != nil {
		t.Fatal(err)
	}
	gz, err := gzip.NewReader(bytes.NewReader(archive))
	if err != nil {
		t.Fatal(err)
	}
	tr := tar.NewReader(gz)
	var names []string
	for {
		header, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			t.Fatal(err)
		}
		names = append(names, header.Name)
	}
	if len(names) != 1 || names[0] != "app.txt" {
		t.Fatalf("archive entries = %v; want only app.txt", names)
	}
}
