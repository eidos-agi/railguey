// railguey is a project-token Railway CLI with no runtime dependency beyond Go.
package main

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const backboardURL = "https://backboard.railway.com/graphql/v2"

type client struct{ token string }
type projectToken struct {
	ProjectID     string `json:"projectId"`
	EnvironmentID string `json:"environmentId"`
}
type project struct {
	ID       string `json:"id"`
	Name     string `json:"name"`
	Services struct {
		Edges []struct {
			Node service `json:"node"`
		} `json:"edges"`
	} `json:"services"`
}
type service struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

func main() {
	if len(os.Args) < 2 || os.Args[1] == "--help" || os.Args[1] == "-h" {
		usage(0)
		return
	}
	if os.Args[1] == "--version" {
		fmt.Println("railguey go-dev")
		return
	}
	var result any
	var err error
	switch os.Args[1] {
	case "services":
		result, err = services(os.Args[2:])
	case "deployments":
		result, err = deployments(os.Args[2:])
	case "status":
		result, err = status(os.Args[2:])
	case "upload-source":
		result, err = uploadSource(os.Args[2:])
	case "doctor":
		result, err = doctor(os.Args[2:])
	default:
		fmt.Fprintf(os.Stderr, "unknown command %q\n", os.Args[1])
		usage(2)
		return
	}
	if err != nil {
		result = map[string]string{"error": err.Error()}
	}
	encoded, _ := json.MarshalIndent(result, "", "  ")
	fmt.Println(string(encoded))
	if err != nil {
		os.Exit(1)
	}
}

func usage(code int) {
	fmt.Fprintln(os.Stderr, "railguey — project-token Railway CLI")
	fmt.Fprintln(os.Stderr, "\nCommands:\n  status WORKSPACE\n  services WORKSPACE\n  deployments WORKSPACE SERVICE [--limit N]\n  upload-source WORKSPACE SERVICE [--message SHA]\n  doctor WORKSPACE")
	if code != 0 {
		os.Exit(code)
	}
}

func workspace(args []string, min int) (string, []string, error) {
	if len(args) < min {
		return "", nil, errors.New("missing required arguments")
	}
	path, err := filepath.Abs(args[0])
	if err != nil {
		return "", nil, err
	}
	return path, args[1:], nil
}

func tokenFor(workspace string) (string, error) {
	for _, name := range []string{".env.local", ".env"} {
		body, err := os.ReadFile(filepath.Join(workspace, name))
		if err != nil {
			continue
		}
		for _, line := range strings.Split(string(body), "\n") {
			line = strings.TrimSpace(line)
			if strings.HasPrefix(line, "RAILWAY_TOKEN=") {
				value := strings.Trim(strings.TrimSpace(strings.TrimPrefix(line, "RAILWAY_TOKEN=")), "\"'")
				if value != "" {
					return value, nil
				}
			}
		}
	}
	if value := strings.TrimSpace(os.Getenv("RAILWAY_TOKEN")); value != "" {
		return value, nil
	}
	return "", fmt.Errorf("no RAILWAY_TOKEN in %s/.env.local, %s/.env, or environment", workspace, workspace)
}

func newClient(workspace string) (*client, error) {
	token, err := tokenFor(workspace)
	if err != nil {
		return nil, err
	}
	return &client{token}, nil
}

func (c *client) gql(query string, variables any, target any) error {
	payload := map[string]any{"query": query}
	if variables != nil {
		payload["variables"] = variables
	}
	body, _ := json.Marshal(payload)
	req, err := http.NewRequest(http.MethodPost, backboardURL, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Project-Access-Token", c.token)
	response, err := (&http.Client{Timeout: 30 * time.Second}).Do(req)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode > 299 {
		data, _ := io.ReadAll(response.Body)
		return fmt.Errorf("Backboard API returned %d: %s", response.StatusCode, strings.TrimSpace(string(data)))
	}
	var envelope struct {
		Data   json.RawMessage `json:"data"`
		Errors json.RawMessage `json:"errors"`
	}
	if err := json.NewDecoder(response.Body).Decode(&envelope); err != nil {
		return err
	}
	if len(envelope.Errors) > 0 && string(envelope.Errors) != "null" {
		return fmt.Errorf("GraphQL error: %s", envelope.Errors)
	}
	return json.Unmarshal(envelope.Data, target)
}

func (c *client) projectToken() (projectToken, error) {
	var out struct {
		ProjectToken projectToken `json:"projectToken"`
	}
	err := c.gql("query { projectToken { projectId environmentId } }", nil, &out)
	return out.ProjectToken, err
}
func (c *client) project(id string) (project, error) {
	var out struct {
		Project project `json:"project"`
	}
	err := c.gql("query project($id: String!) { project(id: $id) { id name services { edges { node { id name } } } } }", map[string]string{"id": id}, &out)
	return out.Project, err
}
func (c *client) serviceID(projectID, name string) (string, error) {
	p, err := c.project(projectID)
	if err != nil {
		return "", err
	}
	for _, edge := range p.Services.Edges {
		if strings.EqualFold(edge.Node.Name, name) {
			return edge.Node.ID, nil
		}
	}
	return "", fmt.Errorf("service %q not found in project", name)
}

func services(args []string) (any, error) {
	ws, _, err := workspace(args, 1)
	if err != nil {
		return nil, err
	}
	c, err := newClient(ws)
	if err != nil {
		return nil, err
	}
	pt, err := c.projectToken()
	if err != nil {
		return nil, err
	}
	p, err := c.project(pt.ProjectID)
	if err != nil {
		return nil, err
	}
	out := make([]map[string]string, 0, len(p.Services.Edges))
	for _, edge := range p.Services.Edges {
		out = append(out, map[string]string{"name": edge.Node.Name, "id": edge.Node.ID})
	}
	return map[string]any{"services": out, "count": len(out)}, nil
}

func deployments(args []string) (any, error) {
	ws, rest, err := workspace(args, 2)
	if err != nil {
		return nil, err
	}
	serviceName := rest[0]
	fs := flag.NewFlagSet("deployments", flag.ContinueOnError)
	limit := fs.Int("limit", 10, "number of deployments")
	if err := fs.Parse(rest[1:]); err != nil {
		return nil, err
	}
	c, err := newClient(ws)
	if err != nil {
		return nil, err
	}
	pt, err := c.projectToken()
	if err != nil {
		return nil, err
	}
	serviceID, err := c.serviceID(pt.ProjectID, serviceName)
	if err != nil {
		return nil, err
	}
	query := "query deployments($input: DeploymentListInput!, $first: Int) { deployments(input: $input, first: $first) { edges { node { id status createdAt url staticUrl canRedeploy canRollback } } } }"
	var out struct {
		Deployments struct {
			Edges []struct {
				Node map[string]any `json:"node"`
			} `json:"edges"`
		} `json:"deployments"`
	}
	err = c.gql(query, map[string]any{"input": map[string]string{"projectId": pt.ProjectID, "serviceId": serviceID}, "first": *limit}, &out)
	if err != nil {
		return nil, err
	}
	items := make([]map[string]any, 0, len(out.Deployments.Edges))
	for _, edge := range out.Deployments.Edges {
		items = append(items, edge.Node)
	}
	return map[string]any{"deployments": items, "count": len(items)}, nil
}

func status(args []string) (any, error) {
	ws, _, err := workspace(args, 1)
	if err != nil {
		return nil, err
	}
	c, err := newClient(ws)
	if err != nil {
		return nil, err
	}
	pt, err := c.projectToken()
	if err != nil {
		return nil, err
	}
	p, err := c.project(pt.ProjectID)
	if err != nil {
		return nil, err
	}
	return map[string]any{"project": p.Name, "projectId": pt.ProjectID, "environmentId": pt.EnvironmentID, "services": p.Services.Edges}, nil
}

func uploadSource(args []string) (any, error) {
	ws, rest, err := workspace(args, 2)
	if err != nil {
		return nil, err
	}
	serviceName := rest[0]
	fs := flag.NewFlagSet("upload-source", flag.ContinueOnError)
	message := fs.String("message", "", "deploy message")
	if err := fs.Parse(rest[1:]); err != nil {
		return nil, err
	}
	c, err := newClient(ws)
	if err != nil {
		return nil, err
	}
	pt, err := c.projectToken()
	if err != nil {
		return nil, err
	}
	serviceID, err := c.serviceID(pt.ProjectID, serviceName)
	if err != nil {
		return nil, err
	}
	body, err := tarball(ws)
	if err != nil {
		return nil, err
	}
	u := fmt.Sprintf("https://backboard.railway.com/project/%s/environment/%s/up", pt.ProjectID, pt.EnvironmentID)
	values := url.Values{"serviceId": {serviceID}}
	if *message != "" {
		values.Set("message", *message)
	}
	u += "?" + values.Encode()
	req, err := http.NewRequest(http.MethodPost, u, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Project-Access-Token", c.token)
	req.Header.Set("Content-Type", "application/gzip")
	response, err := (&http.Client{Timeout: 5 * time.Minute}).Do(req)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	data, _ := io.ReadAll(response.Body)
	if response.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("source upload returned %d: %s", response.StatusCode, strings.TrimSpace(string(data)))
	}
	var result map[string]any
	_ = json.Unmarshal(data, &result)
	result["uploaded"] = true
	result["service"] = serviceName
	result["serviceId"] = serviceID
	result["tarballBytes"] = len(body)
	return result, nil
}

func tarball(root string) ([]byte, error) {
	var out bytes.Buffer
	gz := gzip.NewWriter(&out)
	tw := tar.NewWriter(gz)
	skip := map[string]bool{".git": true, "node_modules": true, ".venv": true, ".env": true, ".env.local": true}
	err := filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		if rel == "." {
			return nil
		}
		if skip[info.Name()] {
			if info.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		if info.IsDir() || !info.Mode().IsRegular() {
			return nil
		}
		header, err := tar.FileInfoHeader(info, "")
		if err != nil {
			return err
		}
		header.Name = filepath.ToSlash(rel)
		if err := tw.WriteHeader(header); err != nil {
			return err
		}
		file, err := os.Open(path)
		if err != nil {
			return err
		}
		_, copyErr := io.Copy(tw, file)
		closeErr := file.Close()
		if copyErr != nil {
			return copyErr
		}
		return closeErr
	})
	if err != nil {
		return nil, err
	}
	if err := tw.Close(); err != nil {
		return nil, err
	}
	if err := gz.Close(); err != nil {
		return nil, err
	}
	if out.Len() > 256*1024*1024 {
		return nil, errors.New("source archive exceeds Railway's 256MB limit")
	}
	return out.Bytes(), nil
}

func doctor(args []string) (any, error) {
	ws, _, err := workspace(args, 1)
	if err != nil {
		return nil, err
	}
	_, tokenErr := tokenFor(ws)
	_, workflowErr := os.Stat(filepath.Join(ws, ".github", "workflows", "deploy.yml"))
	findings := []map[string]string{}
	if tokenErr == nil {
		findings = append(findings, map[string]string{"check": "RAILWAY_TOKEN", "status": "pass"})
	} else {
		findings = append(findings, map[string]string{"check": "RAILWAY_TOKEN", "status": "fail", "message": tokenErr.Error()})
	}
	if workflowErr == nil {
		findings = append(findings, map[string]string{"check": "GitHub Actions deploy workflow", "status": "pass"})
	} else {
		findings = append(findings, map[string]string{"check": "GitHub Actions deploy workflow", "status": "fail", "message": "missing .github/workflows/deploy.yml"})
	}
	return map[string]any{"findings": findings, "healthy": tokenErr == nil && workflowErr == nil}, nil
}
