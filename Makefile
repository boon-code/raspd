
PYTHON := python
RM := rm

all: sdist

.PHONY: sdist clean install

sdist:
	$(PYTHON) setup.py sdist

clean:
	$(RM) -f MANIFEST
	$(RM) -rf dist/

install:
	$(PYTHON) setup.py install
