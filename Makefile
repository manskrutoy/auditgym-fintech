.PHONY: check test demo generate trajectories docker
check:
	python3 -m auditgym check
test:
	python3 -m unittest discover -s tests -t .
demo:
	python3 -m auditgym demo --episode dev/dev_08
generate:
	python3 -m auditgym generate
trajectories:
	python3 -m auditgym run
docker:
	docker build -t auditgym:1.0.0 . && docker run --rm --network none --cpus=2 --memory=4g auditgym:1.0.0
