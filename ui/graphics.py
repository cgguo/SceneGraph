#!/usr/bin/env python
import os
from PySide import QtCore, QtGui
from functools import partial
from SceneGraph import core

from . import node_widgets
from . import handlers

# logger
log = core.log


class GraphException(Exception):
    def __init__(self, message, errors={}):
        super(GraphException, self).__init__(message)

        self.errors = errors


class GraphicsView(QtGui.QGraphicsView):

    tabPressed        = QtCore.Signal()
    statusEvent       = QtCore.Signal(dict)
    selectionChanged  = QtCore.Signal()

    def __init__(self, parent=None, ui=None, opengl=False, debug=False, **kwargs):
        QtGui.QGraphicsView.__init__(self, parent)

        self.log                 = log
        self._parent             = ui
        
        self._scale              = 1
        self.current_cursor_pos  = QtCore.QPointF(0, 0)

        self.initializeSceneGraph(ui.graph, ui, opengl=opengl, debug=debug)
        self.viewport_mode       = self._parent.viewport_mode
        
        # Mouse Interaction
        self.setCacheMode(QtGui.QGraphicsView.CacheBackground)
        self.setRenderHint(QtGui.QPainter.Antialiasing)
        self.setTransformationAnchor(QtGui.QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QtGui.QGraphicsView.AnchorUnderMouse)

        self.setInteractive(True)  # this allows the selection rectangles to appear
        self.setDragMode(QtGui.QGraphicsView.RubberBandDrag)
        self.setRenderHint(QtGui.QPainter.Antialiasing)

        self.setMouseTracking(True)
        self.boxing = False
        self.modifierBoxOrigin = None
        self.modifierBox = QtGui.QRubberBand(QtGui.QRubberBand.Rectangle, self)
        self.scale(1.0, 1.0)

        # context menu
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.showContextMenu)
        self.connectSignals()

    def initializeSceneGraph(self, graph, ui, **kwargs):
        """
        Setup the GraphicsScene.

        params:
            graph (Graph)       - graph instance.
            ui    (QMainWindow) - parent window.
        """
        if ui.use_gl:
            from PySide import QtOpenGL
            self.setViewport(QtOpenGL.QGLWidget())
            log.info('initializing OpenGL renderer.')

        # pass the Graph instance to the GraphicsScene 
        scene = GraphicsScene(self, graph=graph, ui=ui)
        scene.setSceneRect(-5000, -5000, 10000, 10000)
        self.setScene(scene)

    @property
    def viewport_mode(self):
        """
        Returns the current viewport mode.

        return:
            (str) - update mode.
        """
        mode = self.viewportUpdateMode()
        if mode == QtGui.QGraphicsView.ViewportUpdateMode.FullViewportUpdate:
            return 'full'
        if mode == QtGui.QGraphicsView.ViewportUpdateMode.SmartViewportUpdate:
            return 'smart'
        if mode == QtGui.QGraphicsView.ViewportUpdateMode.MinimalViewportUpdate:
            return 'minimal'
        return

    @viewport_mode.setter
    def viewport_mode(self, mode):
        """
        Set the viewport update mode.

        params:
            mode (str) - viewport level (full is slower).
        """
        if mode == 'full':
            mode = QtGui.QGraphicsView.ViewportUpdateMode.FullViewportUpdate

        if mode == 'smart':
            mode = QtGui.QGraphicsView.ViewportUpdateMode.SmartViewportUpdate

        if mode == 'minimal':
            mode = QtGui.QGraphicsView.ViewportUpdateMode.MinimalViewportUpdate
        self.setViewportUpdateMode(mode)
    
    def updateGraphViewAttributes(self):
        """
        Update networkx graph attributes from the current UI.

        TODO: check speed hit on this one
        """
        self.scene().network.graph['view_scale']=self.getScaleFactor()
        self.scene().network.graph['view_center']=self.getCenterPoint()
        self.scene().network.graph['scene_size']=self.getSceneCoordinates()

    def connectSignals(self):
        """
        Connect widget signals.
        """
        self.scene().changed.connect(self.sceneChangedAction)
        self.scene().sceneRectChanged.connect(self.sceneRectChangedAction)
        self.scene().selectionChanged.connect(self.sceneSelectionChangedAction)

    # debug
    def getContentsSize(self):
        """
        Returns the contents size (physical size)
        """
        crect = self.contentsRect()
        return [crect.width(), crect.height()]
    
    def getCenterPoint(self):
        """
        Returns the correct center point of the current view.
        """
        # maps center to a QPointF
        center_point = self.mapToScene(self.viewport().rect().center())
        return (center_point.x(), center_point.y())
    
    def setCenterPoint(self, pos):
        """
        Sets the current scene center point.

        params:
            pos - (tuple) x & y coordinates.
        """
        self.centerOn(pos[0],pos[1])

    def getSceneCoordinates(self):
        """
        Returns the scene size.

        returns:
            (tuple) - coordinates of current scene. (-x, -y, x, y)
        """
        if self.scene():
            return self.scene().sceneRect().getCoords()
        return (0, 0, 0, 0)

    def getTranslation(self):
        """
        Returns the current scrollbar positions.
        """
        return [self.horizontalScrollBar().value(), self.verticalScrollBar().value()]

    def getScaleFactor(self):
        """
        Returns the current scale factor.
        """
        return [self.transform().m11(), self.transform().m22()]

    def updateStatus(self, event):
        """
        Update the parent console widget with the view status.

        params:
            event - (QEvent) event object
        """
        #action.setData((action.data()[0], self.mapToScene(menuLocation)))
        # provide debug feedback
        status = dict(
            view_size = self.getContentsSize(),
            scene_size = self.getSceneCoordinates(),
            zoom_level = self.getScaleFactor(),
            )
 
        if hasattr(event, 'pos'):
            epos = event.pos()
            spos = self.mapToScene(event.pos())
            status['view_cursor'] = (epos.x(), epos.y())            
            status['scene_cursor'] = (spos.x(), spos.y())
            status['scene_pos'] = self.getCenterPoint()

        self.statusEvent.emit(status)

    def wheelEvent(self, event):
        """
        Wheel event to implement a smoother scaling.
        """
        factor = 1.41 ** ((event.delta()*.5) / 240.0)
        self.scale(factor, factor)
        self._scale = factor
        self.updateGraphViewAttributes()

    def viewportEvent(self, event):
        self.updateStatus(event)
        return QtGui.QGraphicsView.viewportEvent(self, event) 

    def mouseMoveEvent(self, event):
        self.updateStatus(event)
        QtGui.QGraphicsView.mouseMoveEvent(self, event)

    def mouseDoubleClickEvent(self, event):
        QtGui.QGraphicsView.mouseDoubleClickEvent(self, event)

    def mousePressEvent(self, event):
        """
        Pan the viewport if the control key is pressed
        """
        self.current_cursor_pos = event.pos()
        if event.modifiers() & QtCore.Qt.ControlModifier:
            self.setDragMode(QtGui.QGraphicsView.ScrollHandDrag)
        else:
            self.setDragMode(QtGui.QGraphicsView.RubberBandDrag)

        if event.button() == QtCore.Qt.RightButton:
            print 'building context menu...'
            self.showContextMenu(event.pos())
        QtGui.QGraphicsView.mousePressEvent(self, event)

    def event(self, event):
        """
        Capture the tab key press event.
        """
        if event.type() == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Tab:
            self.tabPressed.emit()
        return QtGui.QGraphicsView.event(self, event)

    def keyPressEvent(self, event):
        """
        Fit the viewport if the 'A' key is pressed
        """
        selected_nodes = self.scene().selectedNodes()
        if event.key() == QtCore.Qt.Key_A:
            # get the bounding rect of the graphics scene
            boundsRect = self.scene().itemsBoundingRect()            
            
            # resize
            self.fitInView(boundsRect, QtCore.Qt.KeepAspectRatio)
            #self.setSceneRect(boundsRect) # this resizes the scene rect to the bounds rect, not desirable

        if event.key() == QtCore.Qt.Key_F:
            boundsRect = self.scene().selectionArea().boundingRect()
            self.fitInView(boundsRect, QtCore.Qt.KeepAspectRatio)

        # delete nodes & edges...
        elif event.key() == QtCore.Qt.Key_Delete or event.key() == QtCore.Qt.Key_Backspace:
            self.scene().handler.removeSceneNodes(selected_nodes)

        # disable selected nodes
        elif event.key() == QtCore.Qt.Key_D:
            if selected_nodes:
                for node in selected_nodes:
                    node.is_enabled = not node.is_enabled


        self.updateGraphViewAttributes()
        self.scene().update()
        return QtGui.QGraphicsView.keyPressEvent(self, event)

    def get_scroll_state(self):
        """
        Returns a tuple of scene extents percentages
        """
        centerPoint = self.mapToScene(self.viewport().width()/2,
                                      self.viewport().height()/2)
        sceneRect = self.sceneRect()
        centerWidth = centerPoint.x() - sceneRect.left()
        centerHeight = centerPoint.y() - sceneRect.top()
        sceneWidth =  sceneRect.width()
        sceneHeight = sceneRect.height()

        sceneWidthPercent = centerWidth / sceneWidth if sceneWidth != 0 else 0
        sceneHeightPercent = centerHeight / sceneHeight if sceneHeight != 0 else 0
        return sceneWidthPercent, sceneHeightPercent

    def showContextMenu(self, pos):
        """
        Pop up a node creation context menu at a given location.
        """
        menu = QtGui.QMenu()
        menuActions = ['add attribute']
        for action in menuActions:
            #action.setData((action.data()[0], self.mapToScene(pos)))
            menu.addAction(action)
        menu.exec_(self.mapToGlobal(pos))

    def restoreNodes(self, data):
        """
        Undo command.
        """
        selected_nodes = self.selected_nodes()
        self.blockSignals(True)
        for node in selected_nodes:
            node.dagnode.update(**data)
        self.blockSignals(False)
    
    #- Actions -----
    def sceneChangedAction(self, *args):
        """
        Runs when the scene has changed in some manner.
        """
        pass
        
    def sceneRectChangedAction(self, *args):
        #print '# GraphicsView: scene rect changed'
        pass
        
    def sceneSelectionChangedAction(self):
        """
        Runs when the scene selection changes.
        """
        self.selectionChanged.emit()


class GraphicsScene(QtGui.QGraphicsScene):
    """
    Notes:

    self.itemsBoundingRect() - returns the maximum boundingbox for all nodes

    """
    def __init__(self, parent=None, graph=None, ui=None, **kwargs):
        QtGui.QGraphicsScene.__init__(self, parent)

        self.ui          = ui
        self.debug       = ui.debug
        self.edge_type   = ui.edge_type

        # graph
        self.graph       = graph
        self.network     = graph.network

        # temp line for drawing edges
        self.line        = None        

        self.handler     = handlers.SceneHandler(self)
        self.scenenodes  = dict()

    def initialize(self):
        """
        Initialize the scene nodes attributes and
        clear the current scene.
        """
        self.scenenodes=dict()
        self.clear()

    def addNodes(self, dagids):
        """
        Add dag nodes to the current scene.

        params:
            dagnodes (list) - list of dag node/edge objects.
        """
        if type(dagids) not in [list, tuple]:
            dagids = [dagids,]

        log.debug('GraphicsScene: adding %d nodes.' % len(dagids))
        widgets = []
        for dag_id in dagids:
           if dag_id in self.graph.dagnodes:
                dag = self.graph.get(dag_id)
                if isinstance(dag, core.DagNode):              
                    if dag_id not in self.scenenodes:
                        widget = node_widgets.Node(dag)
                        widget._render_effects = self.ui.render_fx

                        # set the debug mode
                        widget.setDebug(self.debug)
                        self.scenenodes[dag.id]=widget
                        self.addItem(widget)
                        widgets.append(widget)

                        widget.nodeChanged.connect(self.nodeChangedEvent)
                        widget.nodeDeleted.connect(self.nodeDeletedEvent)

                # adding an edge
                elif isinstance(dag, core.DagEdge):              
                    if dag_id not in self.scenenodes:
                        # get the source connection node

                        src_widget = self.getNode(dag.src_id)
                        dest_widget = self.getNode(dag.dest_id)

                        # get the relevant connection terminals
                        src_conn_widget = src_widget.getOutputConnection(dag.src_attr)
                        dest_conn_widget = dest_widget.getInputConnection(dag.dest_attr)

                        widget = node_widgets.Edge(dag, src_conn_widget, dest_conn_widget)
                        widget.nodeDeleted.connect(self.nodeDeletedEvent)

                        widget._render_effects = self.ui.render_fx

                        # check that connection is valid. (implement this)
                        if widget.connect_terminal(src_conn_widget) and widget.connect_terminal(dest_conn_widget):
                            # set the debug mode
                            widget.setDebug(self.debug)
                            self.scenenodes[dag.id]=widget
                            self.addItem(widget)
                            widgets.append(widget)
                else:
                    raise GraphException('invalid graph id: "%s"' % dag_id )
        return widgets

    def removeNodes(self, nodes):
        """
        Remove node widgets from the scene.

        params:
            nodes (list) - list of node widgets.
        """
        if type(nodes) not in [list, tuple]:
            nodes = [nodes,]
            
        for node in nodes:
            print '# Scene.removeNodes: ', node
            if isinstance(node, node_widgets.Node):
                print '# signalling graph...'
                self.graph.removeNode(node.dagnode.id)

            if isinstance(node, node_widgets.Edge):
                print 'edge!'
                self.graph.removeEdge(node.dagnode.id)

    def getNodes(self):
        """
        Returns a list of node widgets.

        returns:
            (list) - list of DagNode widgets.
        """
        widgets = []
        for item in self.items():
            if isinstance(item, node_widgets.Node):
                widgets.append(item)
        return widgets

    def getNode(self, name):
        """
        Get a named node widget from the scene.

        params:
            name (str) - node name or id.

        returns:
            (DagNode) - node widget.
        """
        if name in self.scenenodes:
            return self.scenenodes.get(name)

        for id, node in self.scenenodes.iteritems():
            node_name = node.dagnode.name
            if node_name == name:
                return node

    def selectedNodes(self, nodes_only=False):
        """
        Returns a list of selected item widgets.

        returns:
            (list) - list of widgets.
        """
        widgets = []
        selected = self.selectedItems()
        for item in selected:
            if isinstance(item, node_widgets.Node):
                widgets.append(item)

            if isinstance(item, node_widgets.Edge):
                if not nodes_only:
                    widgets.append(item)
        return widgets

    def selectedDagNodes(self):
        """
        Returns a list of selected dag nodes.

        returns:
            (list) - list of selected dag nodes.
        """
        if self.selectedNodes():
            return [n.dagnode for n in self.selectedNodes()]
        return []

    def getEdges(self):
        """
        Returns a list of edge widgets.

        returns:
            (list) - list of Edge widgets.
        """
        edges = []
        for item in self.items():
            if isinstance(item, node_widgets.Edge):
                edges.append(item)
        return edges

    def getEdge(self, *args):
        """
        Return a named edge.
        """
        edges = []
        for edge in self.getEdges():
            if edge.name in args:
                edges.append(edge)
            if edge.source_connection in args:
                if edge.dest_connection in args:
                    edges.append(edge)
        for arg in args:
            if arg in self.scenenodes:
                edges.append(self.scenenodes.get(arg))
        return edges

    def popNode(self, node):
        """
        'Pop' a node from its current chain.

        params:
            node (DagNode) - node widget instance.

        returns:
            (bool) - node was properly removed from its chain.
        """
        return True

    def insertNode(self, node, edge):
        """
        Insert a node into the selected edge chain.

        params:
            node (DagNode) - node widget instance.
            edge (Edge) - edge widget instance.

        returns:
            (bool) - node was properly inserted into the current chain.
        """
        return True

    def mousePressEvent(self, event):
        """
        Draw a line if a connection widget is selected and dragged.
        """
        item = self.itemAt(event.scenePos())
        if event.button() == QtCore.Qt.LeftButton:
            if isinstance(item, node_widgets.Connection):
                if item.isOutputConnection():
                    crect = item.boundingRect()
                    self.line = QtGui.QGraphicsLineItem(QtCore.QLineF(event.scenePos(), event.scenePos()))
                    self.addItem(self.line)
                    self.update(self.itemsBoundingRect())

                # disconnect the edge if this is an input
                if item.isInputConnection():
                    # query the edge(s) attached.
                    edges = item.connections.values()                    
                    if edges:
                        if len(edges) == 1:
                            conn_edge = edges[0]

                            # remove the edge from the connections
                            if conn_edge.disconnect_terminal(item):

                                # todo: call manage?
                                self.graph.removeEdge(conn_edge.dagnode.id)

                                edge_line = conn_edge.getLine()
                                p1 = edge_line.p1()

                                self.line = QtGui.QGraphicsLineItem(QtCore.QLineF(p1, event.scenePos()))
                                self.addItem(self.line)
                                self.update(self.itemsBoundingRect())

        if event.button() == QtCore.Qt.RightButton:
            pass

        QtGui.QGraphicsScene.mousePressEvent(self, event)
        self.update()

    def mouseMoveEvent(self, event):
        """
        Update the line as the user draws.
        """
        item = self.itemAt(event.scenePos())
        if item:
            pass

        # if we're drawing a line...
        if self.line:
            newLine = QtCore.QLineF(self.line.line().p1(), event.scenePos())
            self.line.setLine(newLine)

        QtGui.QGraphicsScene.mouseMoveEvent(self, event)
        self.update()

    def mouseReleaseEvent(self, event):
        """
        Create an edge if the connections are valid.
        """
        if self.line:
            source_items = self.items(self.line.line().p1())
            if len(source_items) and source_items[0] == self.line:
                source_items.pop(0)

            dest_items = self.items(self.line.line().p2())
            if len(dest_items) and dest_items[0] == self.line:
                dest_items.pop(0)

            self.removeItem(self.line)
            if len(source_items) and len(dest_items):

                # these are connection widgets
                source_conn = source_items[0]
                dest_conn = dest_items[0]

                # if we're not dealing with two connections, return without
                # doing anything.
                if not isinstance(source_conn, node_widgets.Connection) or not isinstance(dest_conn, node_widgets.Connection):
                    return

                if self.validateConnection(source_conn, dest_conn):
                    src_dag = source_conn.dagnode
                    dest_dag = dest_conn.dagnode                 
                    edge = self.graph.addEdge(src_dag, dest_dag, src_attr=source_conn.name, dest_attr=dest_conn.name)

        self.line = None
        QtGui.QGraphicsScene.mouseReleaseEvent(self, event)
        self.update()

    def nodeChangedEvent(self, node):
        """
        Update dag node when widget attributes change. 
        Signal the graph that the data has changed as well.

        params:
            node (Node) - node widget.
        """
        if hasattr(node, 'dagnode'):
            # update the 
            pos = (node.pos().x(), node.pos().y())
            node.setToolTip('(%d, %d)' % (pos[0], pos[1]))
            node.dagnode.pos = pos

            # SIGNAL MANAGER (Scene -> Graph)
            self.handler.sceneNodesUpdatedAction([node,])           

    def nodeDeletedEvent(self, node):
        """
        Called when a node is deleted.

        params:
            node (QGraphicsObject) - node (or edge) widget.
        """
        print 'GraphicsScene.nodeDeletedEvent'
        if isinstance(node, node_widgets.Node):
            print 'removing node: ', node.name
            self.removeItem(node)

        if isinstance(node, node_widgets.Edge):
            print 'removing edge: ', node.name
            self.removeItem(node)

    def updateNodesAction(self, dagnodes):
        print 'GraphicsScene: updating %d dag nodes' % len(dagnodes)

    def validateConnection(self, src, dest, force=True):
        """
        When the mouse is released, validate the two connections.

        params:
            src  (Connection) - connection widget
            dest (Connection) - connection widget
            force (bool)      - force the connection

        returns:
            (bool) - connection is valid.
        """
        if self.line:
            if not isinstance(src, node_widgets.Connection) or not isinstance(dest, node_widgets.Connection):
                print 'Error: wrong type.'
                return False

            if src.isInputConnection() or dest.isOutputConnection():
                print 'Error: invalid connection order.'
                return False

            # don't let the user connect input/output on the same node!
            if str(src.dagnode.id) == str(dest.dagnode.id):
                print 'Error: same node connection.'
                return False

            # check here to see if destination can take another connection
            if hasattr(dest, 'is_connectable'):
                if not dest.is_connectable:
                    if not force:
                        log.warning('Error: "%s" is not connectable.' % dest.connection_name)
                        return False

                    # remove the connected edge
                    dest_node = dest.node
                    # edges
                    edges = dest.connections.values()

                    for edge in edges:
                        log.warning('forcing edge removal: "%s"' % edge.name)
                        edge_id = str(edge.dagnode.id)
                        if self.graph.removeEdge(edge_id):
                            continue
                        log.warning('edge removal failed: "%s"' % edge.name)
                    return True

        return True

