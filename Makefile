PYTHON := python
RM := rm

all: sdist

.PHONY: sdist clean install dry-install

sdist:
	$(PYTHON) setup.py sdist

clean:
	$(RM) -f MANIFEST
	$(RM) -rf dist/
	$(RM) -rf build/

install:
	$(PYTHON) setup.py build
	sudo $(PYTHON) setup.py install --record install-log.txt
	sudo insserv raspd
	sudo service raspd restart

dry-install:
	$(PYTHON) setup.py --dry-run install --record install-log.txt
